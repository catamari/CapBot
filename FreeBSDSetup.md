## FreeBSD Jail Setup (FreeNAS)

1. Create a new jail.
2. as root, `pkg update`. This will install the package manager.
3. `pkg upgrade`.
4. Install sudo: `pkg install sudo`.

### Add Admin User
1. as root, run `adduser`.
2. I named this user 'admin'. All default configs, give it a password.
3. as root, `pw group mod wheel -m admin` to give sudo.
4. Run `visudo` to edit sudoers file and uncomment `%wheel ALL=(ALL:ALL) ALL`.
5. `su admin` to switch to this user.

### Add Jail user
- This is the user we'll be running the script as. It should have bare minimum permissions.
1. as root, run `adduser`.
2. Leave all config as default. I'm naming it 'jailuser'.

### Install Python
1. `sudo pkg install Python313`
2. `/usr/local/bin/python3.13 -m ensurepip` to install pip.
3. Install sqlite3 as it's not in the FreeBSD stdlib for some reason: `sudo pkg install -y sqlite py313-sqlite3`
4. Verify sqlite3 package exists: `python3.13 -c "import sqlite3; print(sqlite3.sqlite_version)"`

### Install Git
1. `sudo pkg install git`

### Repo setup
1. `su jailuser` && `cd ~/`
2. `git clone https://github.com/truesharing/CapBot.git`
3. `cd CapBot`
4. `python3.13 -m pip install -r requirements.txt` to install dependencies.

### Setup Env Vars
1. `echo "CAPBOT_TOKEN=X" > env_vars`
2. `echo "GUILD_ID=X" >> env_vars`
3. `echo "CAPBOT_CLAN_NAME=X" >> env_vars`
4. `echo "CAPBOT_PIDFILE=X" >> env_vars`
4. `echo "CAPBOT_CWD=X" >> env_vars`

### Setup Service
1. As admin user, `sudo cp capbot.rc.d.sh /usr/local/etc/rc.d/capbot`
2. `sudo chmod +x /usr/local/etc/rc.d/capbot`.
3. `sudo touch /var/log/capbot.log`
4. `sudo chown jailuser:jailuser /var/log/capbot.log`