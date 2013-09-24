# NrvrCommander - Repository README

NrvrCommander is a Python package for devops and QA automation around
virtual machines, VMware, Enterprise Linux 6.x, Ubuntu LTS, enabling
work with Firefox, Chrome, Selenium, and more.

If you got this from the source repository
(at [github](https://github.com/srguiwiz/nrvr-commander))
and just want to use it, run **./installlocally.py**.

For what is provided in the package, see **src/README.txt**.

Other than src/, files in dev/ are NOT going into the Python package.

Details for hosting on different operating systems (Linux, Mac OS X) are
kept in docs/.

Good example uses (demonstrating utility) are
**dev/examples/make-an-el-vm-001.py** (guest command line Enterprise Linux),
**dev/examples/make-an-ub-vm-002.py** (guest command line Ubuntu), and
**dev/examples/qa/selenium/make-testing-vms-w-snaps-001.py**
(guest GUI Linux running Selenium, although this example as implemented
uses VM snapshots and hence needs VMware Workstation or Fusion, but
one could use most of its techniques without snapshots in VMware Player).

Initially made with certain brand Linux distributions,
and with VMware "personal desktop" machine virtualization,
this code is useful for automation with other operating systems,
physical machines, etc.

This project is about getting stuff done reproducibly.
