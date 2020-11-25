class InventoryScript(object):
    ''' Host inventory parser for ansible using external inventory scripts. '''
 
    def __init__(self, filename=C.DEFAULT_HOST_LIST):
 
        # Support inventory scripts that are not prefixed with some
        # path information but happen to be in the current working
        # directory when '.' is not in PATH.
        # 获取绝对路径
        self.filename = os.path.abspath(filename)
        # 参数
        cmd = [ self.filename, "--list" ]
        try:
            # 尝试调用调用出错或是返回码不为0的话就直接报错
            sp = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            raise errors.AnsibleError("problem running %s (%s)" % (' '.join(cmd), e))
        (stdout, stderr) = sp.communicate()
 
        if sp.returncode != 0:
            raise errors.AnsibleError("Inventory script (%s) had an execution error: %s " % (filename,stderr))
 
        self.data = stdout
        # see comment about _meta below
        self.host_vars_from_top = None
        self.groups = self._parse(stderr)
 
    # 这个方法是核心
    def _parse(self, err):
 
        all_hosts = {}
 
        # not passing from_remote because data from CMDB is trusted
        # 通过json解析， json_dict_bytes_to_unicode
        self.raw  = utils.parse_json(self.data)
        # 递归解析字典、列表、元组去一个字符串，这是一个内置的方法
        self.raw  = json_dict_bytes_to_unicode(self.raw)
 
        # 和group类处理的相同
        all       = Group('all')
        groups    = dict(all=all)
        group     = None
 
        # 有错误输出
        if 'failed' in self.raw:
            sys.stderr.write(err + "\n")
            raise errors.AnsibleError("failed to parse executable inventory script results: %s" % self.raw)
 
        # 获取组信息
        for (group_name, data) in self.raw.items():
 
            # in Ansible 1.3 and later, a "_meta" subelement may contain
            # a variable "hostvars" which contains a hash for each host
            # if this "hostvars" exists at all then do not call --host for each
            # host.  This is for efficiency and scripts should still return data
            # if called with --host for backwards compat with 1.2 and earlier.
 
            # 这个_meta一般为主机设置环境变量，即可以不通过--host再去获取主机的相应信息
            # 这个方法主要是为了省带宽
            if group_name == '_meta':
                if 'hostvars' in data:
                    # 设置这完意，然后就进行下一次循环
                    self.host_vars_from_top = data['hostvars']
                    continue
            # 组名不是all 就实例一个group
            if group_name != all.name:
                group = groups[group_name] = Group(group_name)
            else:
                group = all
            host = None
 
            # data不是字典直接赋值
            if not isinstance(data, dict):
                data = {'hosts': data}
            # is not those subkeys, then simplified syntax, host with vars
            # 看过group的很好理解
            elif not any(k in data for k in ('hosts','vars','children')):
                data = {'hosts': [group_name], 'vars': data}
 
            # hosts在组里面，并且不是列表就报错，不然就添加主机进这个组
            if 'hosts' in data:
                if not isinstance(data['hosts'], list):
                    raise errors.AnsibleError("You defined a group \"%s\" with bad "
                        "data for the host list:\n %s" % (group_name, data))
 
                # 添加主机进这个组
                for hostname in data['hosts']:
                    if not hostname in all_hosts:
                        all_hosts[hostname] = Host(hostname)
                    host = all_hosts[hostname]
                    group.add_host(host)
 
            # 设置组的环境变量，同样做个异常判断不是字段就报错
            # 同上因为主机是列表，而变量是key/value形式
            if 'vars' in data:
                if not isinstance(data['vars'], dict):
                    raise errors.AnsibleError("You defined a group \"%s\" with bad "
                        "data for variables:\n %s" % (group_name, data))
 
                for k, v in data['vars'].iteritems():
                    if group.name == all.name:
                        all.set_variable(k, v)
                    else:
                        group.set_variable(k, v)
 
        # Separate loop to ensure all groups are defined
        # 添加子组
        for (group_name, data) in self.raw.items():
            if group_name == '_meta':
                continue
            if isinstance(data, dict) and 'children' in data:
                for child_name in data['children']:
                    if child_name in groups:
                        groups[group_name].add_child_group(groups[child_name])
 
        # 这里搞定all组
        for group in groups.values():
            if group.depth == 0 and group.name != 'all':
                all.add_child_group(group)
 
        return groups
 
    # 这里就是--host的处理了
    def get_host_variables(self, host):
        """ Runs <script> --host <hostname> to determine additional host variables """
        # 就是前面的"_meta"的东西， 通过主机参数获取他的相应的变量字典
        if self.host_vars_from_top is not None:
            got = self.host_vars_from_top.get(host.name, {})
            return got
 
        # 直接跑
        cmd = [self.filename, "--host", host.name]
        try:
            sp = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            raise errors.AnsibleError("problem running %s (%s)" % (' '.join(cmd), e))
        (out, err) = sp.communicate()
        if out.strip() == '':
            return dict()
        try:
            return json_dict_bytes_to_unicode(utils.parse_json(out))
        except ValueError:
            raise errors.AnsibleError("could not parse post variable response: %s, %s" % (cmd, out))
