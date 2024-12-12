# charms.files
A python package providing file helpers for [Juju](juju.is) charms using the [operator](github.com/canonical/operator) library.
Install from PyPI with the distribution package name `charms.files`.
This is a namespace package using the `charms` namespace. Import it with `import charms.files` or `from charms import files`.
Note that `import charms; charms.files` will not work (unless perhaps you have your own `charms` package loaded ahead of `charms.files` which knows about it).