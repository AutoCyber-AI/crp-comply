# crp-comply-searxng variables:

SEARXNG_REDIS_URL
*******



SEARXNG_SECRET_KEY
*******






# crp-comply-searxng settings:

Source
Source Repo
Constantinos-uni/crp-comply



Disconnect
Root Directory
Configure where we should look for your code. Docs↗
Root directory
/services/crp-comply-searxng
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
crp-comply-searxng.railway.internal
IPv4 & IPv6


This private URL will be functional after the next deployment of this service.

DNS
crp-comply-searxng
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
Replicas are not available for attached volumes.

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

Railpack

Default

App builder developed by Railway. Docs↗

Custom Build Command
Override the default build command that is run when building your app. Docs↗

Build Command
Watch Paths
Gitignore-style rules to trigger a new deployment based on what file paths have changed. Docs↗
Add pattern
Add pattern e.g. /services/crp-comply-searxng/src/**

Deploy
Custom Start Command
Command that will be run to start new deployments. Docs↗

Start Command
Add pre-deploy step (Docs↗)
Teardown
Configure old deployment termination when a new one is started. Docs↗

Cron Schedule
Run the service according to the specified cron schedule.

Add Schedule
Healthcheck Path
Endpoint to be called before a deploy completes to ensure the new deployment is live. Docs↗

Healthcheck Path
Serverless
Containers will scale down to zero and then scale up based on traffic. Requests while the container is sleeping will be queued and served when the container wakes up. Docs↗

Restart Policy
Configure what to do when the process exits. Docs↗
On Failure

Restart the container if it exits with a non-zero exit code.


Number of times to try and restart the service if it stopped due to an error.
Max restart retries
10
Config-as-code
Railway Config File
Manage your build and deployment settings through a config file. Docs↗

Add File Path
Feature-flags



Delete Service
Deleting this service will permanently delete all its deployments and remove it from this environment. This cannot be undone.