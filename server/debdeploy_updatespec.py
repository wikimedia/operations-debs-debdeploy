# -*- coding: utf-8 -*-
import sys

import yaml


class DebDeployUpdateSpec(object):
    '''
    Each update is described in a YAML file, see docs/readme.txt for the data
    format.
    '''

    source = ""
    comment = ""
    update_type = ""
    fixes = {}
    libraries = []
    legit_type = ['tool', 'daemon-direct', 'daemon-disrupt', 'daemon-cluster', 'reboot',
                  'reboot-cluster', 'library']
    downgrade = False

    def __init__(self, updatespec, supported_distros):
        '''
        Parse an update spec file.

        updatespec        : Filename of the update spec file (string)
        supported_distros : These are the distro codenames for which a fixed version can be provided
                            (list of strings)
        '''

        try:
            with open(updatespec, "r") as stream:
                updatefile = yaml.load(stream)

        except IOError:
            print("Error: Could not open {}".format(updatespec))
            sys.exit(1)

        except yaml.scanner.ScannerError as e:
            print("Invalid YAML file:")
            print(e)
            sys.exit(1)

        if "source" not in updatefile:
            print(("Invalid YAML file, you need to specify the source package using the 'source' "
                   "stanza, see the annotated example file for details"))
            sys.exit(1)
        else:
            self.source = updatefile["source"]

        if "update_type" not in updatefile:
            print(("Invalid YAML file, you need to specify the type of update using the "
                   "'update_type' stanza, see the annotated example file for details"))
            sys.exit(1)
        else:
            if updatefile["update_type"] not in self.legit_type:
                print("Invalid YAML file, invalid 'update_type'")
                sys.exit(1)
            self.update_type = updatefile["update_type"]

        if "comment" in updatefile:
            self.comment = updatefile["comment"]

        if "libraries" in updatefile:
            self.libraries = updatefile["libraries"]

        if "downgrade" in updatefile:
            self.downgrade = updatefile["downgrade"]

        if "fixes" not in updatefile:
            print(("Invalid YAML file, you need to specify at least one fixed version using the "
                   "'fixes' stanza, see the annotated example file for details"))
            sys.exit(1)
        else:
            for i in updatefile["fixes"]:
                if len(list(supported_distros.keys())) >= 1:
                    self.fixes[i] = updatefile["fixes"].get(i)
                else:
                    print(("Invalid YAML file, {} is not a supported distribution. You need to "
                           "activate it in /deb/debdeploy.conf".format(i)))
                    sys.exit(1)

# Local variables:
# mode: python
# End:
