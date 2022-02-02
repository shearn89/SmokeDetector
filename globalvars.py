# -*- coding: utf-8 -*-

import sys
import os
import boto3
import botocore.exceptions
from collections import namedtuple
from datetime import datetime
from html.parser import HTMLParser
from html import unescape
from hashlib import md5
from configparser import NoOptionError, ConfigParser
import threading
# noinspection PyCompatibility
import regex
import subprocess as sp
import platform
if 'windows' in platform.platform().lower():
    # noinspection PyPep8Naming
    from _Git_Windows import git, GitError
else:
    # noinspection PyUnresolvedReferences
    from sh.contrib import git


CommitInfo = namedtuple('CommitInfo', ['id', 'id_full', 'author', 'message'])

git_url = git.config("--get", "remote.origin.url").strip()
git_url_split = git_url.split("/")
git_user_repo = "Charcoal-SE/SmokeDetector"
if git_url[0:19] == "https://github.com/":
    git_user_repo = "{}/{}".format(git_url_split[3], git_url_split[4][0:-4])

ssm = boto3.client("ssm")
def get_ssm_parameter(parameter_name):
    parameter = ssm.get_parameter(
            Name=parameter_name,
            WithDecryption=True
    )
    return parameter['Parameter']['Value'].strip()

def git_commit_info():
    try:
        data = sp.check_output(['git', 'rev-list', '-1', '--pretty=%h%n%H%n%an%n%s', 'HEAD'],
                               stderr=sp.STDOUT).decode('utf-8')
    except sp.CalledProcessError as e:
        raise OSError("Git error:\n" + e.output) from e
    _, abbrev_id, full_id, author, message = data.strip().split("\n")
    return CommitInfo(id=abbrev_id, id_full=full_id, author=author, message=message)


def git_ref():
    git_cp = sp.run(['git', 'symbolic-ref', '--short', '-q', 'HEAD'], stdout=sp.PIPE)
    return git_cp.stdout.decode("utf-8").strip()  # not on branch = empty output

# We don't need strip_escape_chars() anymore, see commit message
# of 1931d30804a675df07887ce0466e558167feae57


# noinspection PyClassHasNoInit,PyDeprecation,PyUnresolvedReferences
class GlobalVars:
    on_windows = 'windows' in platform.platform().lower()

    false_positives = []
    whitelisted_users = set()
    blacklisted_users = dict()
    blacklisted_usernames = []
    blacklisted_websites = []
    # set() with the processed version of each blacklisted number pattern.
    blacklisted_numbers = None
    # blacklisted_numbers_raw is a list with the raw patterns read from the blacklisted_numbers.txt file.
    blacklisted_numbers_raw = None
    # set() with the processed version of each watched number pattern.
    watched_numbers = None
    # watched_numbers_raw is a dict() with the keys the raw patterns, with properties
    # for the user and time the pattern was added. Insertion order represents the order of the patterns in the
    # watched_numbers.txt
    watched_numbers_raw = None
    # set() with the normalized, including deobfuscated and normalized, versions of the patterns.
    blacklisted_numbers_normalized = None
    watched_numbers_normalized = None
    # The _full versions are a dict() with key=raw pattern, with tuple with processed and normalized for each.
    # Insertion order is the order they are in within the file.
    blacklisted_numbers_full = None
    watched_numbers_full = None
    bad_keywords = []
    watched_keywords = {}
    ignored_posts = []
    auto_ignored_posts = []
    startup_utc_date = datetime.utcnow()
    startup_utc = startup_utc_date.strftime("%H:%M:%S")
    latest_questions = []
    api_backoff_time = 0
    deletion_watcher = None

    not_privileged_warning = \
        "You are not a privileged user. Please see " \
        "[the privileges wiki page](https://charcoal-se.org/smokey/Privileges) for " \
        "information on what privileges are and what is expected of privileged users."

    experimental_reasons = {  # Don't widely report these
        "potentially bad keyword in answer",
        "potentially bad keyword in body",
        "potentially bad keyword in title",
        "potentially bad keyword in username",
        "potentially bad NS for domain in title",
        "potentially bad NS for domain in body",
        "potentially bad NS for domain in answer",
        "potentially bad ASN for hostname in title",
        "potentially bad ASN for hostname in body",
        "potentially bad ASN for hostname in answer",
        "potentially bad IP for hostname in title",
        "potentially bad IP for hostname in body",
        "potentially bad IP for hostname in answer",
        "potentially problematic NS configuration in title",
        "potentially problematic NS configuration in body",
        "potentially problematic NS configuration in answer",
        "toxic body detected",
        "toxic answer detected",
    }

    parser = HTMLParser()
    parser.unescape = unescape

    code_privileged_users = None

    # these are loaded in GlobalVars.reload()
    commit = None
    commit_with_author = None
    on_branch = None

    s = ""
    s_reverted = ""
    s_norestart_blacklists = ""
    s_norestart_findspam = ""
    apiquota = -1
    bodyfetcher = None
    cookies = {}
    se_sites = []
    why_data = []
    notifications = []
    listen_to_these_if_edited = []
    multiple_reporters = []
    api_calls_per_site = {}
    reason_weights = {}
    metasmoke_ids = {}

    standby_message = ""
    standby_mode = False
    no_se_activity_scan = False
    no_deletion_watcher = False

    ignore_no_se_websocket_activity_lock = threading.Lock()
    ignore_no_se_websocket_activity = False

    api_request_lock = threading.Lock()  # Get this lock before making API requests
    apiquota_rw_lock = threading.Lock()  # Get this lock before reading/writing apiquota

    class PostScanStat:
        """ Tracking post scanning data """
        num_posts_scanned = 0
        post_scan_time = 0
        rw_lock = threading.Lock()

        @staticmethod
        def add_stat(posts_scanned, scan_time):
            """ Adding post scanning data """
            with GlobalVars.PostScanStat.rw_lock:
                GlobalVars.PostScanStat.num_posts_scanned += posts_scanned
                GlobalVars.PostScanStat.post_scan_time += scan_time

        @staticmethod
        def get_stat():
            """ Getting post scanning statistics """
            with GlobalVars.PostScanStat.rw_lock:
                posts_scanned = GlobalVars.PostScanStat.num_posts_scanned
                scan_time = GlobalVars.PostScanStat.post_scan_time
            if scan_time == 0:
                posts_per_second = None
            else:
                posts_per_second = posts_scanned / scan_time
            return (posts_scanned, scan_time, posts_per_second)

        @staticmethod
        def reset_stat():
            """ Resetting post scanning data """
            with GlobalVars.PostScanStat.rw_lock:
                GlobalVars.PostScanStat.num_posts_scanned = 0
                GlobalVars.PostScanStat.post_scan_time = 0

    config_parser = ConfigParser(interpolation=None)

    if os.path.isfile('config') and "pytest" not in sys.modules:
        config_parser.read('config')
    else:
        config_parser.read('config.ci')

    config = config_parser["Config"]  # It's a collections.OrderedDict now

    site_id_dict = {}
    post_site_id_to_question = {}

    location = config.get("location", "Continuous Integration")

    # DNS Configuration
    # Configure resolver based on config options, or System, configure DNS Cache in
    # thread-safe cache as part of dnspython's resolver system as init options,
    # control cleanup interval based on **TIME** like a regular DNS server does.
    #
    # # Explicitly defining fallback= for fallback values in bool and float getters, in order to
    # #    avoid IDE complaints -- tward
    dns_nameservers = config.get("dns_resolver", "system").lower()
    dns_cache_enabled = config.getboolean("dns_cache_enabled", fallback=True)
    dns_cache_interval = config.getfloat("dns_cache_cleanup_interval", fallback=300.0)

    class MSStatus:
        """ Tracking metasmoke status """
        ms_is_up = True
        counter = 0
        rw_lock = threading.Lock()

        @staticmethod
        def set_up():
            """ Set metasmoke status to up """
            # Private to metasmoke.py
            with GlobalVars.MSStatus.rw_lock:
                GlobalVars.MSStatus.ms_is_up = True

        @staticmethod
        def set_down():
            """ Set metasmoke status to down """
            # Private to metasmoke.py
            with GlobalVars.MSStatus.rw_lock:
                GlobalVars.MSStatus.ms_is_up = False

        @staticmethod
        def is_up():
            """ Query if metasmoke status is up """
            with GlobalVars.MSStatus.rw_lock:
                current_ms_status = GlobalVars.MSStatus.ms_is_up
            return current_ms_status

        @staticmethod
        def is_down():
            """ Query if metasmoke status is down """
            return not GlobalVars.MSStatus.is_up()

        # Why implement failed() and succeeded() here, as they will only be called in metasmoke.py?
        # Because get_failure_count() need to be exposed to global, so it is more convenient
        # to implement failed() and succeeded() here.
        @staticmethod
        def failed():
            """ Indicate a metasmoke connection failure """
            with GlobalVars.MSStatus.rw_lock:
                GlobalVars.MSStatus.counter += 1

        @staticmethod
        def succeeded():
            """ Indicate a metasmoke connection success """
            with GlobalVars.MSStatus.rw_lock:
                GlobalVars.MSStatus.counter = 0

        @staticmethod
        def get_failure_count():
            """ Get consecutive metasmoke connection failure count """
            with GlobalVars.MSStatus.rw_lock:
                failure_count = GlobalVars.MSStatus.counter
            return failure_count

        @staticmethod
        def reset_ms_status():
            """ Reset class GlobalVars.MSStatus to default values """
            with GlobalVars.MSStatus.rw_lock:
                GlobalVars.MSStatus.ms_is_up = True
                GlobalVars.MSStatus.counter = 0

    def get_config_value(config, key):
        """ get config variables from a secret store, or environment, or config file """
        if key in os.environ:
            print(f"found {key} in env")
            return os.environ[key]
        elif config.get(key):
            if config.get("secret_store") == "aws-ssm":
                ssm_key = config.get(key)
                print(f"found {key} as secret in config, attempting ssm call")
                try:
                    return get_ssm_parameter(ssm_key)
                except botocore.exceptions.ClientError as error:
                    if error.response['Error']['Code'] == 'ParameterNotFound':
                        print("parameter not found in SSM, continuing")
                    elif error.response['Error']['Code'] == 'ValidationException':
                        print("parameter name invalid, continuing")
                    else:
                        print(error)
            print(f"found {key} in config")
            return config.get(key)
        return None

    # sensitive variables
    chatexchange_u = get_config_value(config, 'ChatExchangeU')
    chatexchange_p = get_config_value(config, 'ChatExchangeP')
    metasmoke_key = get_config_value(config, "metasmoke_key")

    metasmoke_host = config.get("metasmoke_host")
    metasmoke_ws_host = config.get("metasmoke_ws_host")

    git_name = config.get("git_username", "SmokeDetector")
    git_email = config.get("git_useremail", "smokey@erwaysoftware.com")

    github_username = config.get("github_username")
    # TODO: get these from SSM
    github_password = config.get("github_password")
    # TODO: get these from SSM
    github_access_token = config.get("github_access_token")

    # TODO: get these from SSM
    perspective_key = config.get("perspective_key")

    flovis_host = config.get("flovis_host")
    flovis = None

    # Miscellaneous
    log_time_format = config.get("log_time_format", "%H:%M:%S")

    # Blacklist privileged users from config
    se_blacklisters = regex.sub(r"[^\d,]", "", config.get("se_blacklisters", "")).split(",")
    mse_blacklisters = regex.sub(r"[^\d,]", "", config.get("mse_blacklisters", "")).split(",")
    so_blacklisters = regex.sub(r"[^\d,]", "", config.get("so_blacklisters", "")).split(",")

    # Create a set of blacklisters equivalent to what's used in code_privileged_users.
    config_blacklisters = set()
    for id in se_blacklisters:
        if id:
            config_blacklisters.add(("stackexchange.com", int(id)))

    for id in mse_blacklisters:
        if id:
            config_blacklisters.add(("meta.stackexchange.com", int(id)))

    for id in so_blacklisters:
        if id:
            config_blacklisters.add(("stackoverflow.com", int(id)))

    # If the config has it, get a list of the detection reasons which are considered valid.
    # The list is semicolon separated.
    valid_detection_reasons = config.get("valid_detection_reasons", None)
    if valid_detection_reasons is not None:
        valid_detection_reasons = valid_detection_reasons.split(";")

    # If the config has it, get a list of the detection IDs which are considered valid.
    # The list is semicolon separated.
    valid_rule_ids = config.get("valid_rule_ids", None)
    if valid_rule_ids is not None:
        valid_rule_ids = valid_rule_ids.split(";")

    # environ_or_none replaced by os.environ.get (essentially dict.get)
    bot_name = os.environ.get("SMOKEDETECTOR_NAME", git_name)
    bot_repo_slug = os.environ.get("SMOKEDETECTOR_REPO", git_user_repo)
    bot_repository = "//github.com/{}".format(bot_repo_slug)
    chatmessage_prefix = "[{}]({})".format(bot_name, bot_repository)

    valid_content = """This is a totally valid post that should never be caught. Any blacklist or watchlist item that triggers on this item should be avoided. java.io.BbbCccDddException: nothing wrong found. class Safe { perfect valid code(int float &#%$*v a b c =+ /* - 0 1 2 3 456789.EFGQ} English 中文Français Español Português Italiano Deustch ~@#%*-_/'()?!:;" vvv kkk www sss ttt mmm absolute std::adjacent_find (power).each do |s| bbb end ert zal l gsopsq kdowhs@ xjwk* %_sooqmzb xjwpqpxnf.  Please don't blacklist disk-partition.com, it's a valid domain (though it also gets spammed rather frequently)."""  # noqa: E501

    @classmethod
    def reload(cls):
        cls.commit = commit = git_commit_info()

        cls.commit_with_author = "`{}` ({}: {})".format(
            commit.id, commit.author, commit.message)

        # We don't want to escape `[` and `]` when they are within code.
        split_commit_with_author = cls.commit_with_author.split('`')
        split_length = len(split_commit_with_author)
        for index in range(0, split_length, 2):
            split_commit_with_author[index] = split_commit_with_author[index].replace('[', '\\[').replace(']', '\\]')
        # There's not an even number of ` characters, so the parsing hack failed, but we assume the last one needs
        # escaping.
        if not split_length % 2:
            split_commit_with_author[-1] = split_commit_with_author[-1].replace('[', '\\[').replace(']', '\\]')

        cls.commit_with_author_escaped = '`'.join(split_commit_with_author)

        cls.on_branch = git_ref()
        cls.s = "[ {} ] SmokeDetector started at [rev {}]({}/commit/{}) (running on {}, Python {})".format(
            cls.chatmessage_prefix, cls.commit_with_author_escaped, cls.bot_repository,
            cls.commit.id, cls.location, platform.python_version())
        cls.s_reverted = \
            "[ {} ] SmokeDetector started in [reverted mode](" \
            "https://charcoal-se.org/smokey/SmokeDetector-Statuses#reverted-mode) " \
            "at [rev {}]({}/commit/{}) (running on {})".format(
                cls.chatmessage_prefix, cls.commit_with_author_escaped, cls.bot_repository,
                cls.commit.id, cls.location)
        cls.s_norestart_blacklists = \
            "[ {} ] Blacklists reloaded at [rev {}]({}/commit/{}) (running on {})".format(
                cls.chatmessage_prefix, cls.commit_with_author_escaped, cls.bot_repository,
                cls.commit.id, cls.location)
        cls.s_norestart_findspam = \
            "[ {} ] FindSpam module reloaded at [rev {}]({}/commit/{}) (running on {})".format(
                cls.chatmessage_prefix, cls.commit_with_author_escaped, cls.bot_repository,
                cls.commit.id, cls.location)
        cls.standby_message = \
            "[ {} ] SmokeDetector started in [standby mode](" \
            "https://charcoal-se.org/smokey/SmokeDetector-Statuses#standby-mode) " \
            "at [rev {}]({}/commit/{}) (running on {})".format(
                cls.chatmessage_prefix, cls.commit_with_author_escaped, cls.bot_repository,
                cls.commit.id, cls.location)


GlobalVars.PostScanStat.reset_stat()
GlobalVars.MSStatus.reset_ms_status()
GlobalVars.reload()
