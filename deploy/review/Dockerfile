# actions/runner v2.338.2 images/Dockerfile; immutable official image, no runner registration.
FROM ghcr.io/actions/actions-runner:2.338.2@sha256:759a1d94a15b05941aba5196974ff43fe15b4cbba29b694b35cbc32a1166b232
USER root
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
# The release's Docker client/buildx are already present. gh is needed by Dependabot and scoreboard.
RUN curl -fsSL https://github.com/cli/cli/releases/download/v2.103.3/gh_2.103.3_linux_amd64.tar.gz -o /tmp/gh.tgz \
    && echo '4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d  /tmp/gh.tgz' | sha256sum -c - \
    && tar -xzf /tmp/gh.tgz -C /tmp gh_2.103.3_linux_amd64/bin/gh \
    && install /tmp/gh_2.103.3_linux_amd64/bin/gh /usr/bin/gh \
    && rm -rf /tmp/gh.tgz /tmp/gh_2.103.3_linux_amd64 \
    && mv /home/runner /opt/runner-dist && install -d -o runner -g runner -m 0755 /home/runner
# The entrypoint prepares the job root as root, then runs the listener as the image's `runner`.
COPY entrypoint.sh job-started.sh job-completed.sh /opt/sextant-jit/
RUN chmod 0555 /opt/sextant-jit/*.sh
ENV ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/sextant-jit/job-started.sh \
    ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/sextant-jit/job-completed.sh
ENTRYPOINT ["/opt/sextant-jit/entrypoint.sh"]
