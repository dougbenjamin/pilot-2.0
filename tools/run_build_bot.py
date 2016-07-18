# Copyright European Organization for Nuclear Research (CERN)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# You may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Martin Barisits, <martin.barisits@cern.ch>, 2015
# - Wen Guan, <wen.guan@cern.ch>, 2016

import commands
import datetime
import json
import os
import requests
import sys
import subprocess
import time

requests.packages.urllib3.disable_warnings()

project_url = "https://api.github.com/repos/PanDAWMS/pilot-2.0/pulls"
split_str = "\n####PILOT##ATUO##TEST####\n"


def needs_testing(mr):
    needs_testing = True

    issue_url = mr['issue_url']
    resp = requests.get(url=issue_url)
    issue = json.loads(resp.text)
    labels = [label['name'] for label in issue['labels']]

    pushed_at = mr['head']['repo']['pushed_at']
    updated_at = issue['updated_at']

    pushed_at_time = time.mktime(datetime.datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").timetuple())
    updated_at_time = time.mktime(datetime.datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").timetuple())

    if pushed_at_time < updated_at_time and ('Tests: OK' in labels or 'Tests: FAIL' in labels):
        needs_testing = False
    return needs_testing


def update_pull_request(url, token, data):
    result = requests.post(url=url,
                           headers={"Content-Type": "application/json",
                                    "Authorization": "token %s" % token},
                           data=json.dumps(data))
    if result.status_code == 200 or result.status_code == 201:
        print 'OK'
    else:
        print 'ERROR'
        print result.content


def list_substract(_list, substraction):
    for obj in substraction:
        try:
            _list.remove(obj)
        except ValueError:
            pass


def update_merge_request(merge_request, test_result, for_manual, comment, token):
    print '  Updating Merge request and putting comment ...'
    resp = requests.get(url=merge_request['issue_url'])
    issue = json.loads(resp.text)
    labels = [label['name'] for label in issue['labels']]

    list_substract(labels, ['Tests: OK', 'Tests: FAIL', 'Tests: MANUAL'])

    labels.append('Tests: ' + 'OK' if test_result and not for_manual
                  else 'MANUAL' if test_result else 'FAIL')

    data = {'labels': labels, 'body': '%s%s%s' % (merge_request['body'].split(split_str)[0], split_str, comment)}
    update_pull_request(merge_request['issue_url'], token, data)


def prepare_repository_before_testing():
    # Fetch all
    print '  git fetch --all --prune'
    if commands.getstatusoutput('git fetch --all --prune')[0] != 0:
        print 'Error while fetching all'
        sys.exit(-1)

    # Rebase master/dev
    print '  git rebase origin/dev dev'
    if commands.getstatusoutput('git rebase origin/dev dev')[0] != 0:
        print 'Error while rebaseing dev'
        sys.exit(-1)
    print '  git rebase origin/master master'
    if commands.getstatusoutput('git rebase origin/master master')[0] != 0:
        print 'Error while rebaseing master'
        sys.exit(-1)


def test_output(command, title="SOME TEST", test=lambda x: len(x) != 0):
    command = ("source .venv/bin/activate;"
               "pip install -r tools/pip-requires;pip install -r tools/pip-requires-test;"  # maybe do these in a
                                                                                            # separate call?
               ) + command
    process = subprocess.Popen(['sh', '-c', command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = process.communicate()[0]

    if test(out):
        return ''

    return '##### ' + title + ":\n```\n" + out + "\n```\n"


def test_request(merge_request):
    tests_passed = True
    error_lines = ''

    # Check for Cross Merges
    if merge_request['head']['ref'].lower().startswith('patch'):
        print '  Checking for cross-merges:'
        commits = commands.getoutput('git log master..remotes/%s/%s | grep ^commit' %
                                     (merge_request['head']['label'].split(":")[0],
                                      merge_request['head']['label'].split(":")[1]))
        for commit in commits.splitlines():
            commit = commit.partition(' ')[2]
            if commands.getstatusoutput('git branch --contains %s | grep dev' % commit)[0] == 0:
                print '    Found cross-merge problem with commit %s' % commit
                tests_passed = False
                error_lines += '##### CROSS-MERGE TESTS:\n'
                error_lines += '```\n'
                error_lines += 'This patch is suspicious. It looks like there are feature-commits pulled into' \
                               ' the master branch!\n'
                error_lines += '```\n'
                break

    # Checkout the branch to test
    print '  git checkout remotes/%s' % (merge_request['head']['label'].replace(":", "/"))
    if commands.getstatusoutput('git checkout remotes/%s' % (merge_request['head']['label'].replace(":", "/")))[0] != 0:
        print 'Error while checking out branch'
        sys.exit(-1)

    cwd = os.getcwd()
    os.chdir(root_git_dir)

    error_lines += test_output("nosetests -v", title="UNIT TESTS", test=lambda x: x.endswith("OK\n"))
    error_lines += test_output("flake8 .", title="FLAKE8")
    error_lines += test_output('git diff HEAD^ HEAD|grep -P "^(?i)\+((.*#\s*NOQA:?\s*|(\s*#\s*flake8:\s*noqa\s*))$"',
                               title="BROAD NOQA'S")
    noqas = test_output('git diff HEAD^ HEAD|grep -P "^(?i)\+.*#\s*NOQA:\s*[a-z][0-9]{0,3}(\s*,\s*[a-z][0-9]{0,3})*$"',
                        title="JUST NOQA'S")

    tests_passed = tests_passed and error_lines == ''

    error_lines += noqas

    for_manual_merge = noqas != 0

    error_lines = '#### BUILD-BOT TEST RESULT: ' + 'OK' if tests_passed and not for_manual_merge\
        else 'FOR MANUAL MERGE' if tests_passed else 'FAIL' + '\n\n' + error_lines

    os.chdir(cwd)

    return error_lines, tests_passed, for_manual_merge


def start_test(merge_request, token):
    print 'Starting testing for MR %s ...' % merge_request['head']['label']
    # Add remote to user
    commands.getstatusoutput('git remote add %s %s' % (merge_request['head']['label'].split(":")[0],
                                                       merge_request['head']['repo']['git_url']))

    prepare_repository_before_testing()
    error_lines, tests_passed, for_manual = test_request(merge_request)

    update_merge_request(merge_request=merge_request, test_result=tests_passed, comment=error_lines, token=token,
                         for_manual=for_manual)

    # Checkout original master
    print '  git checkout master'
    if commands.getstatusoutput('git checkout master')[0] != 0:
        print 'Error while checking out master'
        sys.exit(-1)

print 'Checking if a job is currently running ...'
if os.path.isfile('/tmp/pilot_test.pid'):
    # Check if the pid file is older than 90 minutes
    if os.stat('/tmp/pilot_test.pid').st_mtime < time.time() - 60 * 90:
        os.remove('/tmp/pilot_test.pid')
        open('/tmp/pilot_test.pid', 'a').close()
    else:
        sys.exit(-1)
else:
    open('/tmp/pilot_test.pid', 'a').close()

root_git_dir = commands.getstatusoutput('git rev-parse --show-toplevel')[1]

# Load private_token
print 'Loading private token ...'
try:
    with open(root_git_dir + '/.githubkey', 'r') as f:
        private_token = f.readline().strip()
except IOError:
    print 'No github keyfile found at %s' % root_git_dir + '/.githubkey'
    sys.exit(-1)

# Load state file
print 'Loading state file ...'
try:
    with open('/tmp/pilotbuildbot.states') as data_file:
        states = json.load(data_file)
except IOError or ValueError:
    states = {}

# Get all open merge requests
print 'Getting all open merge requests ...'
resp = requests.get(url=project_url, params={'state': 'open'})
merge_request_list = json.loads(resp.text)
for merge_request in merge_request_list:
    print 'Checking MR %s -> %s if it needs testing ...' % (merge_request['head']['label'],
                                                            merge_request['base']['label'])
    if 'dev' in merge_request['base']['label'] and needs_testing(merge_request):
        print 'YES'
        start_test(merge_request=merge_request, token=private_token)
    else:
        print 'NO'

print 'Writing state file ...'
with open('/tmp/pilotbuildbot.states', 'w') as outfile:
    json.dump(states, outfile)

os.remove('/tmp/pilot_test.pid')
