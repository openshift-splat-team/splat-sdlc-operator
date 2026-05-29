# Design Documentation

Design documentation is to be structured in the form of an enhancement. https://github.com/openshift-splat-team/enhancements/blob/master/guidelines/enhancement_template.md

# Feature Development

## Shared Skills for Agents
https://github.com/openshift-eng/ai-helpers/ is a canonical location for sharing Claude skills. When deciding to create a new skill for an agent, see if there is already a close match.  If there is, determine if you can implement the relevant skill in python and enhance your agents.

## Supportability
https://github.com/openshift-splat-team/enhancements/blob/master/guidelines/supportability.md

## Creating Commits
https://github.com/openshift-splat-team/enhancements/blob/master/guidelines/commit_and_pr_text.md

## Repository Tests
Each repository has a set of presubmit tests. These presubmit tests are defined in openshift/release. All required tests should be run for a given PR if possible. You will likely have to reimplement how some of these tests are run.

## Staging

### Working Org
You will not create PRs against the openshift org. You will use a staging org or github user to make changes. The feature architect will create an upstream pull request themselves when satisfied. 

#### Repository Globbing
Multiple stories may impact a single repository. Rather than having multiple PRs for a single repository for a given feature, a single, atomic branch will be created for each repository. Individual stories will have their own commits(see creating commits).

## Workflow

1. Intake feature from Jira. This will be in the form of an epic, or a feature. If an epic does not exist, you will create one.
2. Create a design document PR. The design document will be in the form of an OpenShift enhancement.
2.a. Create a story for the design document review and attach it to the epic.
2.b. Require the design document PR to be approved before continuing.  If the design document PR is closed, the associated story should be closed as "Won't do".
3. Once the design document PR is approved, comment back to the epic with the proposed list of stories. Comments are to be made as a Red Hat Employee.
3.a. Process responses to this comment to refine the stories. 
3.b. Once the epic is commented with "stories approved", go ahead and create the stories and attach them to the epic.
4. Size and prioritize the stories.
5. Set depedency links between the stories in Jira.
6. Implement changes in Github
6.a. Identify and fork impacted repositories(s)
6.b. Create branch specific to the feature in each repository
6.c. Create pull request(s). Each pull request should be labeled with "agent-hold" to prevent the agents from processing comments or updates on the PR. We want to give humans the chance to review first.
6.d. Monitor each pull request. If the agent-hold label is dropped from the PR, process new comments and reset agent-hold when done.

