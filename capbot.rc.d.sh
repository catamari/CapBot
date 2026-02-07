#!/bin/sh

# PROVIDE: capbot
# REQUIRE: LOGIN DAEMON
# KEYWORD: shutdown

. /etc/rc.subr

name="capbot"
rcvar=${name}_enable

load_rc_config $name

: ${capbot_enable="YES"}
: ${capbot_args=""}
: ${capbot_user="jailuser"}
: ${capbot_cwd="/home/jailuser/CapBot"}
: ${capbot_workdir="/home/jailuser/CapBot"}
: ${capbot_env_file="/home/jailuser/CapBot/env_vars"}

# This must match the path in CapBot/env_vars
pidfile="/var/run/${name}/${name}.pid"
# This is a script that runs git pull then starts run.py
command="/home/jailuser/CapBot/runbot"
# We need this for 'status' to work correctly as it doesn't know what the process type is otherwise since we're not running python directly.
procname="/usr/local/bin/python3.13"
capbot_user="jailuser"
capbot_chdir="/home/jailuser/CapBot"

start_precmd="${name}_prestart"

capbot_prestart()
{
    # NOTE: capbot/run.py needs to write to this path!
    install -d -o jailuser /var/run/capbot/
}

run_rc_command "$1"