#!/bin/sh

# PROVIDE: capbot
# REQUIRE: LOGIN DAEMON
# KEYWORD: shutdown

. /etc/rc.subr

name="capbot"
rcvar="${name}_enable"

load_rc_config $name

: ${capbot_enable:="YES"}
: ${capbot_user:="jailuser"}
: ${capbot_group:="jailuser"}
: ${capbot_workdir:="/home/jailuser/CapBot"}
: ${capbot_env_file:="/home/jailuser/CapBot/env_vars"}
: ${capbot_command:="/usr/local/bin/python3.13"}
: ${capbot_script:="/home/jailuser/CapBot/capbot/capbot.py"}
: ${capbot_pidfile:="/tmp/capbot.pid"}
: ${capbot_logfile:="/var/log/capbot.log"}

command="/usr/sbin/daemon"
command_args="-f -p ${capbot_pidfile} -u ${capbot_user} \
    -o ${capbot_logfile} -m 3 \
    -c ${capbot_workdir} \
    -p ${capbot_pidfile} \
    ${capbot_command} ${capbot_script}"

start_precmd="${name}_prestart"
stop_cmd="${name}_stop"

capbot_prestart()
{
    install -d -o ${capbot_user} -g ${capbot_group} ${capbot_workdir}
    install -d -o ${capbot_user} -g ${capbot_group} /var/run
    touch ${capbot_logfile}
    chown ${capbot_user}:${capbot_group} ${capbot_logfile}

    # Always update code before starting
    echo "prestart: workdir=${capbot_workdir}" >> "${capbot_logfile}"
    su -m "${capbot_user}" -c "cd '${capbot_workdir}' && /bin/pwd && /usr/local/bin/git rev-parse --is-inside-work-tree && /usr/local/bin/git pull" \
    >> "${capbot_logfile}" 2>&1 || echo "WARNING: git pull failed" >> "${capbot_logfile}"

}

capbot_stop()
{
    if [ -f "${capbot_pidfile}" ]; then
        kill "$(cat ${capbot_pidfile})" 2>/dev/null || true
    fi
}

run_rc_command "$1"