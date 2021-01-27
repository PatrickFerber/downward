#! /usr/bin/env python3

from collections import defaultdict
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
        print("{} merge(s) have more than "
              "{} parents:".format(len(bad_merges), max_parents))
        print("\n".join("Error: {}".format(x) for x in bad_merges))
        return False
    else:
        return True


def check_branch_name_in_commit_messages():
    commits = subprocess.check_output(
        ["git", "log", "--all", "--pretty=%H;%s"]
    ).decode().splitlines()
    invalid_commits = [
        c for c in commits
        if not REGEX_COMMIT_MESSAGE_BRANCH.match(c[c.find(";") + 1:])]
    if len(invalid_commits) > 0:
        print(
            "{} commit message(s) do not prepend a valid branch name:".format(
                len(invalid_commits)))
        print("\n".join("Error: {}".format(x) for x in invalid_commits))
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
        print("{} commit(s) associated to a branch ref state(s) that they "
              "belong to a different branch".format(len(inconsistent_commits)))
        print("\n".join("Error: {}".format(x) for x in inconsistent_commits))
        return False
    else:
        return True


RULE_SINGLE_ROOT = "single_root"
RULE_SINGLE_PARENT = "single_parent_on_main_or_same_branch"
RULE_MERGE_INTO_NEW_BRANCH = "merge_into_new_branch"
RULE_MERGE_FIRST_PARENT_SAME_BRANCH = "merge_first_parent_same_branch"
RULE_MERGE_ISSUE_WITH_ITSELF = "merge_issue_branch_with_itself"
RULE_MERGE_INVALID_BRANCH_INTO_MAIN = "merge_invalid_branch_into_main"
RULE_MERGE_ISSUE_INTO_ISSUE = "merge_issue_into_issue"

ERROR_RULES = [
    RULE_SINGLE_ROOT, RULE_MERGE_INTO_NEW_BRANCH,
    RULE_MERGE_INVALID_BRANCH_INTO_MAIN, RULE_MERGE_FIRST_PARENT_SAME_BRANCH]
WARNING_RULES = [
    RULE_SINGLE_PARENT, RULE_MERGE_ISSUE_WITH_ITSELF, RULE_MERGE_ISSUE_INTO_ISSUE]


def _check_0_parent_consistency(commit_hash, commit_branch, rule_violations):
    if commit_branch != MAIN:
        rule_violations[RULE_SINGLE_ROOT].append(
            "Commit '{}' ({}) has no parent, but is not the root of {"
            "}".format(commit_hash, commit_branch, MAIN))


def _check_1_parent_consistency(
        commit_hash, commit_branch, parent_branch, rule_violations):
    # commit on main -> parent on main
    # commit not on main -> parent on same branch or on main branch
    if parent_branch != MAIN and parent_branch != commit_branch:
        rule_violations[RULE_SINGLE_PARENT].append(
            "Commit '{}' ({}) has its parent on a another branch which is not "
            "main: '{}'".format(
                commit_hash, commit_branch,
                parent_branch if parent_branch else "BRANCH UNKNOWN"))


def _check_2_parent_consistency(
        commit_hash, commit_branch, parent_branches, rule_violations):
    def _add_violation(rule, message):
        rule_violations[rule].append(message.format(
                commit_hash, commit_branch, ", ".join(parent_branches)))

    assert len(parent_branches) == 2
    first_parent, second_parent = parent_branches
    "Commit '{0}' ({1}) has parents on disallowed/discourage branches or "
    "has an invalid parent order: {2}"
    if all(x != commit_branch for x in parent_branches):
        _add_violation(
            RULE_MERGE_INTO_NEW_BRANCH,
            "Commit '{0}' ({1}) creates a new branch by merging {2}.")
    elif first_parent != commit_branch:
        _add_violation(
            RULE_MERGE_FIRST_PARENT_SAME_BRANCH,
            "Merge '{0}' ({1}) should have its own branch as first parent ("
            "parents: {2}).")
    elif commit_branch == MAIN:
        # commit on main -> first parent main, others issue*
        assert first_parent == MAIN
        if not REGEX_ISSUE_BRANCH.match(second_parent):
            _add_violation(
                RULE_MERGE_INVALID_BRANCH_INTO_MAIN,
                "Commit '{0}' ({1}) merges a forbidden branch into %s ("
                "parents: {2})." % MAIN)
    else:
        assert first_parent == commit_branch
        assert False, "TODO: continue"
        if second_parent == commit_branch:
            _add_violation(
                RULE_MERGE_ISSUE_WITH_ITSELF,
            )

        elif second_parent != MAIN:
            _add_violation(RULE_MERGE_ISSUE_INTO_ISSUE)


def check_branch_parent_consistency():
    rule_violations = defaultdict(list)  # stores the messages to output
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
        if timestamp < TIMESTAMP_LEGACY:
            pass  # continue
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
            _check_0_parent_consistency(
                commit_hash, commit_branch, rule_violations)
        elif len(parent_branches) == 1:
            _check_1_parent_consistency(
                commit_hash, commit_branch, parent_branches[0], rule_violations)
        elif len(parent_branches) == 2:
            _check_2_parent_consistency(
                commit_hash, commit_branch, parent_branches, rule_violations)
        # commits with more than 2 parents are already reported as error

    count_warnings = sum(len(rule_violations[rule]) for rule in WARNING_RULES)
    if count_warnings > 0:
        print("Warning: {} commit(s) have an undesired parent "
              "relationship.".format(count_warnings))
        for rule in WARNING_RULES:
            if len(rule_violations[rule]) > 0:
                print("\n".join("Warning: {}".format(x) for x in rule_violations[rule]))
    count_errors = sum(len(rule_violations[rule]) for rule in ERROR_RULES)
    if count_errors > 0:
        print("Error: {} commit(s) have an prohibited parent "
              "relationship.".format(count_errors))
        for rule in ERROR_RULES:
            if len(rule_violations[rule]) > 0:
                print("\n".join("Error: {}".format(x) for x in rule_violations[rule]))
        return False
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
