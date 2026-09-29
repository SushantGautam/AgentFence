# agentfence -> /etc/profile.d/10-agentfence.sh
#
# 1. Site-wide cplt policy for every user, existing accounts included.
#    Only set if the user has not chosen their own.
# 2. Sandboxed agent shims ahead of the real binaries on PATH.
#
# Harmless if cplt is not installed.

if [ -z "${CPLT_CONFIG:-}" ] && [ -r /etc/agentfence/cplt.toml ]; then
    CPLT_CONFIG=/etc/agentfence/cplt.toml
    export CPLT_CONFIG
fi

case ":${PATH}:" in
    *:/opt/agentfence/bin:*) ;;
    *) PATH="/opt/agentfence/bin:${PATH}"; export PATH ;;
esac
