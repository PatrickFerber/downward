#! /usr/bin/env python3

import datetime
import re
import subprocess
import sys

LEGACY_BRANCH_NAMES = ["issue329test", "ijcai-2011", "hcea-cleanup",
                       "raz-ipc-integration", "emil-new-integration"]
PATTERN_ISSUE_BRANCHES = r"issue\d+|{}".format("|".join(LEGACY_BRANCH_NAMES))
REGEX_ISSUE_BRANCH = re.compile(PATTERN_ISSUE_BRANCHES)
REGEX_COMMIT_MESSAGE_BRANCH = re.compile(
    r"\[(main|{}|release-\d\d\.\d\d)\].*".format(PATTERN_ISSUE_BRANCHES))

REF_HEADS_PREFIX = "refs/heads/"
MAIN = "main"


def convert_to_datetime(timestamp):
    return datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %z")


TIMESTAMP_LEGACY = convert_to_datetime("2020-07-10 23:59:59 +0200")


def check_at_most_two_parents():
    max_parents = 2
    bad_merges = subprocess.check_output(
        ["git", "log", "--all", "--min-parents={}".format(max_parents + 1),
         "--pretty=%H;%s"]
    ).decode().splitlines()
    if len(bad_merges) > 0:
        print("The following merges have more than "
              "{} parents:".format(max_parents))
        print("\n".join(bad_merges))
        return False
    else:
        return True


def check_branch_name_in_commit_messages():
    commits = subprocess.check_output(
        ["git", "log", "--all", "--pretty=%H;%s"]
    ).decode().splitlines()
    invalid_commits = [
        c for c in commits
        if REGEX_COMMIT_MESSAGE_BRANCH.match(c[c.find(";") + 1:]) is None]
    if len(invalid_commits) > 0:
        print(
            "{} commit message(s) do not prepend a valid branch name:".format(
                len(invalid_commits)))
        print("\n".join(invalid_commits))
        return False
    else:
        return True


def check_branch_head_consistent():
    inconsistent_commits = []
    branch_heads = subprocess.check_output(
        ["git", "show-ref", "--heads"]
    ).decode().splitlines()
    for branch_head in branch_heads:
        commit_hash, head_branch = branch_head.split()
        assert head_branch.startswith(REF_HEADS_PREFIX)
        head_branch = head_branch[len(REF_HEADS_PREFIX):]

        commit_message = subprocess.check_output(
            ["git", "log", "--pretty=%s", "-n", "1", commit_hash]
        ).decode()
        msg_branch = REGEX_COMMIT_MESSAGE_BRANCH.match(commit_message)
        if msg_branch is None:
            # 'check_branch_name_in_commit_messages' reports these commits
            continue
        msg_branch = msg_branch.group(1) if msg_branch else msg_branch

        if msg_branch != head_branch:
            inconsistent_commits.append(
                "'{}' belongs to branch '{}', but claims to belong to '{"
                "}'.".format(commit_hash, head_branch, msg_branch))

    if len(inconsistent_commits) != 0:
        print("\n".join(inconsistent_commits))
        return False
    else:
        return True


def check_branch_parent_consistency():
    inconsistent_commits = []

    commits = subprocess.check_output(
        ["git", "log", "--all", "--pretty=%H;%P;%ai;%s"]
    ).decode().splitlines()
    # Parsed entry format: (HASH_COMMIT, [HASH_PARENT_i, ...], DATE, MESSAGE)
    commits = [c.split(";", 3) for c in commits]
    for c in commits:
        c[1] = c[1].split()
        c[2] = convert_to_datetime(c[2])
    hash2message = {c[0]: c[3] for c in commits}

    for commit_hash, parents, timestamp, commit_message in commits:
        commit_branch = REGEX_COMMIT_MESSAGE_BRANCH.match(commit_message)
        if commit_branch is None:
            continue  # another test will report this error
        commit_branch = commit_branch.group(1)
        parent_branches = []
        for parent_hash in parents:
            assert parent_hash in hash2message
            pbranch = REGEX_COMMIT_MESSAGE_BRANCH.match(hash2message[parent_hash])
            parent_branches.append(pbranch.group(1) if pbranch else pbranch)

        if len(parent_branches) == 0:
            if commit_branch != MAIN:
                inconsistent_commits.append(
                    "Commit '{}' ({}) has no parent, but is not the root of {"
                    "}".format(commit_hash, commit_branch, MAIN))

        elif len(parent_branches) == 1:
            if timestamp < TIMESTAMP_LEGACY:
                continue
            # commit on main -> parent on main
            # commit not on main -> parent on same branch or on main branch
            if parent_branches[0] != MAIN and parent_branches[0] != commit_branch:
                inconsistent_commits.append(
                    "Commit '{}' ({}) has its parent on a disallowed branch: "
                    "'{}'".format(commit_hash, commit_branch, parent_branches[0]))

        else:
            if timestamp < TIMESTAMP_LEGACY:
                continue
            # We do not care if more than 2 parents are present. This is checked
            # by check_at_most_two_parents
            if commit_branch == MAIN:
                # commit on main -> first parent main, others issue*
                if (parent_branches[0] != MAIN or
                        any(not REGEX_ISSUE_BRANCH.match(x)
                            for x in parent_branches[1:])):
                    inconsistent_commits.append(
                        "Commit '{}' ({}) has parents on disallowed branches or "
                        "has an invalid parent order: {}".format(
                            commit_hash, commit_branch, ", ".join(parent_branches)))
            else:
                # commit on X -> first parent has to be on X, other has to be main
                if (parent_branches[0] != commit_branch or
                        any(x != MAIN for x in parent_branches[1:])):
                    inconsistent_commits.append(
                        "Commit '{}' ({}) has parents on disallowed branches or "
                        "has an invalid parent order: {}".format(
                            commit_hash, commit_branch, ", ".join(parent_branches)))

    if len(inconsistent_commits) != 0:
        print("\n".join(inconsistent_commits))
        return False
    else:
        return True


def main():
    results = []
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("check_"):
            print("Running {}".format(test_name))
            results.append(test())

    if all(results):
        print("All history checks passed")
    else:
        print("Some history checks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
