# -*- coding: utf-8 -*-

import ConfigParser, sys

class DebDeployConfig(object):
    '''
    Class to read/provide the system-wide configuration of the debdeploy master component.
    It contains the following variables:

    supported_distros: List of strings of supported distros (per Debian/Ubuntu codename)
    server_groups: Dictionary of Salt grains which define a group of servers. A server group
                   can be defined by multiple Salt grains.
    '''
    supported_distros = []
    server_groups = {}
    
    def __init__(self, configfile):
        config = ConfigParser.ConfigParser()
        try:
            if len(config.read(configfile)) == 0:
                print "/etc/debdeploy.conf doesn't exist, you need to create it."
                print "See /usr/share/doc/debdeploy-master/examples/debdeploy.conf"
                sys.exit(1)
        except:
            print "Failed to open", configfile
            sys.exit(1)

        if not config.has_section("distros") or not config.has_option("distros", "supported"):
            print "Could not read list of supported distributions, make sure", configfile, "contains a section [distros] and an option 'supported'"
            sys.exit(1)

        self.supported_distros = [x.strip() for x in config.get("distros", "supported").split(",")]

        if len(self.supported_distros) < 1:
            print "You need to specify at least one supported distribution in /etc/debdeploy.conf"
            sys.exit(1)

        if not config.has_section("serverlists"):
            print "Warning: No serverlists are defined, but that means that only the implicit group 'all' is available."
        else:
            if len(config.options("serverlists")) == 0:
                print "Warning: No serverlists are defined, but that means that only the implicit group 'all' is available."
            else:
                for i in config.options("serverlists"):
                    if len(config.get("serverlists", i)) > 0:
                        self.server_groups[i] = [x.strip() for x in config.get("serverlists", i).split(",")]
                    else:
                        print "Malformed server list, at least one grain must be specified for the server group", i
                        sys.exit(1)
                
# Local variables:
# mode: python
# End:







