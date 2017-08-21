
Summary
-------

debdeploy allows the deployment of software updates in Debian (or Debian-based)
environments on a large scale. It is based on Cumin; updates are
initiated via the debdeploy tool running on the Cumin master. Servers
can be grouped into arbitrary sets of servers/services based on the
Cumin syntax.

Basic setup
-----------

Install debdeploy-server on the Cumin master. Install debdeploy-client
on all clients to be managed. The necessary dependencies will be pulled in.

The Debian packaging installs a basic configuration in
/etc/debdeploy.conf on the Cumin master:

- You might need to customise the list of supported distros (this also
  allows Debian derivatives like Ubuntu, but they must be Debian/apt
  based).

- Each update file can be used on various server groups. The server
  groups are defined via the Cumin host syntax.

- [libraries] maintains a preconfigured list of library base names,
  which are suggested by generate-debdeploy-spec, see below.

Defining an update
------------------

Each update is defined via an update file (specified in YAML). You can
e.g. check these into a git repository to ease review and accountability.
These update specs are only specified once and can then be applied to
the various server groups.

generate-debdeploy-spec guides you through the creation of an update
spec.

Here's an example for such an update definition:

----------------
source: openssl
comment:
update_type: library
fixes:
        stretch: 1.0
        jessie: 1.1
        trusty: 1.2
libraries:
      - libssl
      - libcrypto
----------------

debdeploy operates on Debian source packages. The reason is
that you may have different binary packages installed across your
fleet. Some systems may e.g. only have php5-cli installed, while
others may use several further PHP packages. debdeploy determines the
installed binary packages per source package and updates every
installed binary package.

The "comment" is mostly for informational purposes, it can e.g. denote
CVE IDs for security vulnerabilities.

The update_type configures the rollout behaviour:

tool            -> The updated packages is an enduser tool, can be
                   rolled-out immediately.
daemon-direct   -> Daemons which are restarted during update, but which
                   do no affect existing users
daemon-disrupt  -> Daemons which are restarted during update, where the
                   users notice an impact. The update procedure is almost
                   identical, but "daemon-disrupt" displays additional
                   warnings, runs some sanity checks and allows to
                   automatically disable Icinga checks during the restarts.
reboot          -> Lowlevel component which requires a system reboot
                   (e.g. kernel/glibc/dbus). After installing the update, the
                   system reboot(s) can be managed subsequently.
library         -> After a library is updated, programs may need to be
                   restarted to fully effect the change. In addition
                   to libraries, some applications may also fall under this rule,
                   e.g. when updating QEMU, you might need to restart
                   virtual machines. After installing the update, the
                   service restarts can be managed centrally.

The "fixes" option describes the fixed package version per distro release. If
a fix doesn't apply to a distribution, it can be left blank.

"libraries" specifies a list of library base names, which are used to
determine necessary process restarts after a library upgrade. If
preconfigured in /etc/debdeploy.conf, the library base names are
proposed when generating an update spec.


Deploying an update
-------------------

First you need to create an update spec as outlined above. Now you
can deploy the update with the "deploy" command. "testsystem" here
refers to a host alias definition in Cumin.

debdeploy deploy -u elinks.yaml -s testsystem

The update will run via Cumin.

If anything is awry, you can revert an update using the rollback
command, e.g.

debdeploy rollback -u elinks.yaml -s testsystem

Note that in some cases the version to be rolled back might no longer
be available via apt. In most cases it will still be available in the
local apt cache of the system. 


Restart detection / handling
----------------------------

If you update a tool like, say, Emacs nothing needs to be done in
addition to deploying the update. However, if you're updating a
library, you usually need to perform restarts as well. If you
update e.g. openssl, then all processes using the old version of
openssl will continue to use a copy of the old version. Only when
restarting the process the update will be fully effected. Such
update specs carry the "library" type. Note that this also applies
to some programs with long-running child processes, if you're e.g.
updating QEMU, the same applies. Another example are language
runtimes, if you are e.g. using daemons written in Java or Python,
these processes need to be restarted as well.

When deploying an update for such a "library", debdeploy provides
restart detection using the "query_restart" command. It returns a
list of processes which need to be restarted. This may look like this:




Restarts are intentionally not made automatically for a number of
reasons:
- The effects of a restart may potentially disrupt operation, so
  it should be made at the discretion of the ops person.
- In some cases a restart may simply be waived, e.g. if your web
  server is automatically restarted for nightly code deployments
  anyway. 
- The mechanism to detect service restarts, also applies to non-daemon
  processes for which the restart mechanism isn't automatically
  detectable. E.g. if someone has simply started something in a screen
  session.
  

Dealing with legacy binary packages
-----------------------------------

debdeploy operates on source packages. When an update is deployed
all currently installed binary packages are queried. If a system
has been upgraded from an earlier release and if some outdated
binary packages are still around, upgrades may fail with the error
message:
"The version to be installed could not be found. It might have been
superceded by a more recent version or the apt source is incomplete"

This happens since debdeploy explicitly specifies the version to
upgrade to, but for those outdated binaries thet version is not
available. An example:

You're trying to upgrade the bind9 source package. In Debian wheezy
the binary package name for the ISC DNS shared library is libdns88,
while in Debian jessie, the package name is libdns100. If you are
trying to upgrade bind9 on a jessie system which still has libdns88
installed you, the minion will detect that libdns88 is from the bind9
source package and try to upgrade to the version specified in the YAML
file (which doesn't exist on jessie any longer).

It's recommended to prune those outdated binary packages after
distribution upgrades. Alternatively you can add a local blacklist
by adding a config file /etc/debdeploy-minion.conf. It contains
a blacklist of binary packages, see the shipped example file.











