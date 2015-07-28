
Summary
-------

debdeploy is based on salt to reuse it's authentication and transfer
capabilities. Updates are initiated via the debdeploy tool running
on the salt master. Servers can be grouped into arbitrary sets of
servers/services based on Salt grains.

Basic setup
-----------

Install debdeploy-master on the salt master. Install debdeploy-minion
on all salt minions. The necessary dependencies will be pulled in.

The Debian packaging installs a basic configuration in
/etc/debdeploy.conf:

- You might need to customise the list of supported distros (this also
  allows Debian derivatives like Ubuntu, but they must be Debian/apt
  based).

- Each update file can be used on various server groups. The server
  groups are defined via Salt grains (one or several). You need to
  configure a name for each group of grains.




Defining an update
------------------

Each update is defined via an update file (specified in YAML). You can
e.g. check these into a git repository to ease review and accountability.
These update specs are only specified once and can then be applied to
the various server groups.

Here's an example for such an update definition:

----------------
source: elinks
comment: CVE-2015-0123
update_type: tool
fixes:
        jessie: 0.12~pre6-10
        trusty: 0.12~pre5-8ubuntu2
        precise:0.12~pre5-3ubuntu1
----------------

debdeploy operates on Debian source packages. The reason is
that you may have different binary packages installed across your
fleet. Some systems may e.g. only have php5-common installed, while
others may use several further PHP packages. debdeploy determines the
installed binary packages per source package and updates them.

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
                   to librarries, some applications may also fall under this rule,
                   e.g. when updating QEMU, you might need to restart
                   virtual machines. After installing the update, the
                   service restarts can be managed centrally.

These are planned, but not yet implemented:
daemon-cluster  -> Clustered daemons, when updating, the invididual
                   hosts are taken out of the cluster, updated and
                   finally readded
reboot-cluster  -> Clustered systems, which are taken out of the
                   cluster, updated, rebooted and finally re-added

The "fixes" option describes the fixed package per source package. If
a fix doesn't apply to a distribution, it can be left blank.


Deploying an update
-------------------

First you need to create an update spec as outlined above. Now you
can deploy the update with the deploy command:

debdeploy deploy -u elinks.yaml -s testsystem

The update will run asynchronously via Salt. You can validate the
status of the deployment via the status-deploy command, e.g.:

debdeploy status-deploy -u elinks.yaml -s testsystem

It will print out a summary like this:

  puppet-jmm-salt-client01.puppet.eqiad.wmflabs:
    Updated packages:
      elinks-data: 0.12~pre6-5 -> 0.12~pre6-10
       elinks: 0.12~pre6-5+b2 -> 0.12~pre6-10 
  Deployment summary:
  Number of hosts in this deployment run: 1
  No packages were added
  No packages were removed
  Updated packages:
  elinks: 0.12~pre6-5+b2 -> 0.12~pre6-10 on 1 hosts
  elinks-data: 0.12~pre6-5 -> 0.12~pre6-10 on 1 hosts

If anything is awry, you can revert an update using the rollback
command, e.g.

debdeploy rollback -u elinks.yaml -s testsystem

Note that in some cases the version to be rolled back might no longer
be available via apt. In most cases it will still be available in the
local apt cache of the system. The status of a rollback can be queried
using the rollback-status command, e.g.

debdeploy status-rollback -u elinks.yaml -s testsystem


Restart detection / handling

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

When deploying an update for such a "library", debdeploy includes
automatic restart detection. The deploy run returns a list of
processes which need to be restarted. This may look like this:



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
  

debdeploy simplifies mass-restarts of services using the "restart"
command. It also operates on groups of servers using the same set
of grains. Since there are multiple ways to restart a service in an
Ubuntu/Debian environment (sysv init scripts, upstart jobs, systemd
unit files) and the method can vary across supported releases (e.g.
on wheezy a service may use /etc/init.d/foo and on jessie
/lib/systemd/unit/foo.service), only the name of the process binary
is passed. debdeploy automatically detects the service to restart.
If a service fails to restart, an error is flagged.

Here's an example:

-----------------
debdeploy restart -s testsystem -p /usr/sbin/ntpd -p /usr/sbin/lldpd
Restarting services. Use --verbose to also display non-failing restarts.
puppet-jmm-salt-client01.puppet.eqiad.wmflabs:
   /usr/sbin/lldpd sucessfully restarted
      /usr/sbin/ntpd sucessfully restarted
      Restart summary:

/usr/sbin/lldpd successfully restarted on 1 out of 1 hosts.
/usr/sbin/ntpd successfully restarted on 1 out of 1 hosts.
-----------------















