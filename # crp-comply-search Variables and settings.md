# crp-comply-search Variables

10 Service Variables

Shared Variable

Raw Editor

New Variable

graph of shared variable pointed to multiple services
Keep variables in sync across services

Create a shared variable in Project Settings or promote an existing service variable to a shared variable via the ⋮ icon.

Configure Shared Variables
View Docs
Trying to connect a database? Add Variable


CRP_COMPLY_SEARCH_API_KEY an opensll rand -hex 64 results
*******



CRP_COMPLY_SEARCH_BACKEND
*******



CRP_COMPLY_SEARCH_DDG_DELAY
*******



CRP_COMPLY_SEARCH_PROFILE
*******



CRP_COMPLY_SEARXNG_URL
*******



CRP_COMPLY_WEBSEARCH_BACKEND
*******



PIP_DISABLE_PIP_VERSION_CHECK
*******



PIP_NO_CACHE_DIR
*******



PYTHONDONTWRITEBYTECODE
*******



PYTHONUNBUFFERED
*******

EVERYTHING ELSE IS SET AS YOU TOLD ME. 



# crp-comply-search settings:

Settings
Filter settings
Filter Settings...

/
Source
Source Repo
Constantinos-uni/crp-comply



Disconnect
Root Directory
Configure where we should look for your code. Docs↗
Root directory
/services/crp-comply-search
Branch connected to production
Changes made to this GitHub branch will be automatically pushed to this environment.
master

Disconnect
Auto deploys when pushed to GitHub

Disable
Wait for CI
Trigger deployments after all GitHub actions have completed successfully.

Networking
Public Networking
Access to this service publicly through HTTP or TCP

Generate Domain

Custom Domain

TCP Proxy
Private Networking
Communicate with this service from within the Railway network.
crp-comply-search.railway.internal
IPv4 & IPv6


Ready to talk privately ·
You can also simply call me
crp-comply-search

DNS
crp-comply-search
.railway.internal

Endpoint name available!


Cancel

Update
Outbound IPv6
Enable your service to make outbound connections to IPv6 destinations.

Scale
Regions & Replicas
Deploy replicas per region for horizontal scaling.
US West (California, USA)

Replicas
1
Replica
Multi-region replicas are only available on the Pro plan.

Learn More↗
Replica Limits
Allocate a maximum vCPU and Memory for each replica.
CPU: 8 vCPU

Plan limit: 8 vCPU

Memory: 8 GB

Plan limit: 8 GB

Upgrade for higher limits
Build
Builder
The value is set in
/services/crp-comply-search/railway.toml
Open file↗

Dockerfile

Dockerfile

Build with a Dockerfile using BuildKit. Docs↗

Watch Paths
Gitignore-style rules to trigger a new deployment based on what file paths have changed. Docs↗
Add pattern
Add pattern e.g. /services/crp-comply-search/src/**

Deploy
Custom Start Command
Command that will be run to start new deployments. Docs↗
The value is set in
/services/crp-comply-search/railway.toml
Open file↗
Start command
python -m crp_comply_search
Add pre-deploy step (Docs↗)
Teardown
Configure old deployment termination when a new one is started. Docs↗

Cron Schedule
Run the service according to the specified cron schedule.

Add Schedule
Healthcheck Path
Endpoint to be called before a deploy completes to ensure the new deployment is live. Docs↗
The value is set in
/services/crp-comply-search/railway.toml
Open file↗
Healthcheck Path
/health
Healthcheck Timeout
Number of seconds we will wait for the healthcheck to complete. Docs↗
The value is set in
/services/crp-comply-search/railway.toml
Open file↗
Healthcheck Timeout
30
Serverless
Containers will scale down to zero and then scale up based on traffic. Requests while the container is sleeping will be queued and served when the container wakes up. Docs↗

Restart Policy
Configure what to do when the process exits. Docs↗
The value is set in
/services/crp-comply-search/railway.toml
Open file↗
On Failure

Restart the container if it exits with a non-zero exit code.


Number of times to try and restart the service if it stopped due to an error.
The value is set in
/services/crp-comply-search/railway.toml
Open file↗
Max restart retries
5
Config-as-code
Railway Config File
Manage your build and deployment settings through a config file. Docs↗

Add File Path
Feature-flags

# Attached volumes

radiant-achievement-volume
Metrics
Settings
Connection
Mount Path
Directory that this volume is mounted to in crp-comply-searxng
Mount path
/var/lib/searxng-crp
Size
Volume Size
The maximum size of the volume. You are only charged for the amount of data stored.
5.00 GB



