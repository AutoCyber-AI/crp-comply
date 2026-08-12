# Old searxng variables and settings for comparison to ensure our one is correct

## Variables
7 Service Variables

Shared Variable

Raw Editor

New Variable

graph of shared variable pointed to multiple services
Keep variables in sync across services

Create a shared variable in Project Settings or promote an existing service variable to a shared variable via the ⋮ icon.

Configure Shared Variables
View Docs
Trying to connect a database? Add Variable


BASE_URL
*******




PORT
*******



SEARXNG_SECRET
*******



SEARXNG_SETTINGS_PATH
*******



UWSGI_SETTINGS_PATH
*******



UWSGI_THREADS
*******



UWSGI_WORKERS
*******






## Settings

Source
Source Repo
Constantinos-uni/searxng



Disconnect
Add Root Directory (used for build and deploy steps. Docs↗)
Branch connected to production
Changes made to this GitHub branch will be automatically pushed to this environment.
main

Disconnect
Auto deploys when pushed to GitHub

Disable
Wait for CI
Trigger deployments after all GitHub actions have completed successfully.

Networking
Public Networking
Access your application over HTTP with the following domains
searxng-production-8a81.up.railway.app




Domain
searxng-production-8a81
.up.railway.app

Edit Port
Update your domain or choose a target port


Cancel

Update

Custom Domain

TCP Proxy
Private Networking
Communicate with this service from within the Railway network.
searxng.railway.internal
IPv4 & IPv6


Ready to talk privately ·
You can also simply call me
searxng

DNS
searxng
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

Dockerfile

Automatically Detected

Build with a Dockerfile using BuildKit. Docs↗

Dockerfile Path
The absolute path to your Dockerfile in the repository.
Dockerfile path
Dockerfile
Watch Paths
Gitignore-style rules to trigger a new deployment based on what file paths have changed. Docs↗
Add pattern
Add pattern e.g. /src/**

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



