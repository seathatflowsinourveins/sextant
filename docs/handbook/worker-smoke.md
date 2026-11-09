# Hosted dsh worker smoke test

This file was created by the first dispatched hosted dsh worker. It proves
that a `workflow_dispatch` run can make a documentation change, open a pull
request into `gate`, and leave the rest of the repository untouched.

The worker runs one dsh headless job on a GitHub-hosted runner, with the
repository hard-lines bundle loaded. The pull request is the acceptance
evidence for X2.
