# mac-cloud-backup

A macOS app that backs up your MySQL databases, S3 buckets, and GitHub repos. Double-click to run.

## What it does

- **MySQL/SQL Server** — dumps everything: tables, data, views, stored procedures, functions, triggers, events. Uses a single transaction so nothing gets locked.
- **Amazon S3** — downloads all files from your buckets. Only grabs what's changed on subsequent runs.
- **GitHub** — clones all repos (including private ones) with all branches.

Config is encrypted with a password on first run so credentials aren't stored in plain text.

## Setup

```bash
git clone https://github.com/mosha3t/github-s3-mysql-backup.git
cd github-s3-mysql-backup
cp config.example.yaml config.yaml
```

Edit `config.yaml` with your database host, AWS keys, and GitHub token. Then build the app:

```bash
./build_app.sh
```

That's it. Double-click `Cloud Backup.app` to run. First time it'll ask you to set a password — after that, `config.yaml` gets encrypted and deleted.

## Config

See [config.example.yaml](config.example.yaml) for all options. You can disable any service by setting `enabled: false`.

```yaml
backup_directory: ~/Desktop/Cloud Backups

database:
  enabled: true
  type: "mysql"
  host: "your-db-host.com"
  port: 3306
  username: "backup_readonly"
  password: "your_password"
  databases: []    # empty = back up all databases

s3:
  enabled: true
  aws_access_key_id: "AKIA..."
  aws_secret_access_key: "..."
  region: "us-east-1"
  buckets:
    - "my-bucket"

github:
  enabled: true
  personal_access_token: "ghp_..."
  organization: "your-org-or-username"
  include_private: true
```

## Security

Use read-only credentials. The backup user should never have write access.

**MySQL** — create a read-only user:

```sql
CREATE USER 'backup_readonly'@'%' IDENTIFIED BY 'strong_password';
GRANT SELECT, SHOW VIEW, PROCESS, TRIGGER, EVENT, EXECUTE ON *.* TO 'backup_readonly'@'%';
FLUSH PRIVILEGES;
```

**S3** — create an IAM user with `AmazonS3ReadOnlyAccess` policy only.

**GitHub** — create a token with `repo` scope at [github.com/settings/tokens](https://github.com/settings/tokens).

## CLI usage

You can also run it from the terminal without the app:

```bash
python3 backup.py                 # back up everything
python3 backup.py --only db       # database only
python3 backup.py --only github   # github only
python3 backup.py --only db s3    # database + s3
```

## Backups structure

```
~/Desktop/Cloud Backups/
└── 2025-01-15_14-30-00/
    ├── database/
    │   ├── mydb.sql
    │   └── ...
    ├── s3/
    │   └── bucket-name/
    ├── github/
    │   └── org-name/
    │       └── repo-name/
    └── backup_log.txt
```

## Requirements

- macOS 10.15+
- Python 3.8+ (auto-installed if missing)
- Git (for GitHub backups)

Python packages (`pyyaml`, `boto3`, `requests`, `pymysql`, `pymssql`, `cryptography`) are installed automatically on first run.

## License

MIT
