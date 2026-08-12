# Redis variables


REDIS_PASSWORD
*******



REDIS_PUBLIC_URL
*******




REDIS_URL
*******



REDISHOST
*******



REDISPASSWORD
*******



REDISPORT
*******



REDISUSER
*******






## Redis variables note:
This variable references a public endpoint through this variable:

REDIS_PUBLIC_URL -> RAILWAY_TCP_PROXY_DOMAIN
Connecting to a public endpoint will incur egress fees. That might happen if this variable, REDIS_PUBLIC_URL, is used to establish a connection to a database or another service.

You can avoid the egress fees by switching to a private endpoint (e.g., RAILWAY_PRIVATE_DOMAIN). Check out our documentation for more information!


# Redis settings:

ettings
Filter settings
Filter Settings...

/
Source
Source Image
redis:8.2.1


Configure auto updates


Disconnect
Minor and Patch Updates Available

Upgrade to 8.6.2

Networking
Public Networking
Connect to your service over TCP using a proxied domain and port
trolley.proxy.rlwy.net:53297

:6379




Generate Domain

Custom Domain
Private Networking
Communicate with this service from within the Railway network.
redis.railway.internal
IPv4 & IPv6


Ready to talk privately ·
You can also simply call me
redis

DNS
redis
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
Deploy
Custom Start Command
Command that will be run to start new deployments. Docs↗
Start command
/bin/sh -c "rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH"
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
Feature-flags


# Redis deploy details

7 Variables

Deployed via Docker Image

redis:8.2.1

Dockerhub

sha:5fa2e

Configuration

Build

Builder

Railpack

Deploy

Start command

/bin/sh -c "rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH"

# Redis deploy logs -- needs troubleshooting to ensure all warnings/errors are covered

You reached the start of the range
May 5, 2026, 1:24 PM
Mounting volume on: /var/lib/containers/railwayapp/bind-mounts/1e698e57-1bf4-4216-9416-e4f89edd27c1/vol_vylli7b8s9pidb93
Starting Container
1:M 05 May 2026 03:24:49.181 * <bf> 	{ cf-bucket-size      :         2 }
1:M 05 May 2026 03:24:49.180 * monotonic clock: POSIX clock_gettime
1:M 05 May 2026 03:24:49.181 * <bf> 	{ cf-initial-size     :      1024 }
Starting Redis Server
1:M 05 May 2026 03:24:49.181 * Running mode=standalone, port=6379.
1:M 05 May 2026 03:24:49.181 * <bf> 	{ cf-max-iterations   :        20 }
1:M 05 May 2026 03:24:49.181 * <bf> RedisBloom version 8.2.0 (Git=unknown)
1:C 05 May 2026 03:24:49.180 # WARNING Memory overcommit must be enabled! Without it, a background save or replication may fail under low memory condition. Being disabled, it can also cause failures without low memory condition, see https://github.com/jemalloc/jemalloc/issues/1328. To fix this issue add 'vm.overcommit_memory = 1' to /etc/sysctl.conf and then reboot or run the command 'sysctl vm.overcommit_memory=1' for this to take effect.
1:M 05 May 2026 03:24:49.181 * <bf> 	{ bf-initial-size     :       100 }
1:M 05 May 2026 03:24:49.181 * <bf> Registering configuration options: [
1:C 05 May 2026 03:24:49.180 * oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo
1:M 05 May 2026 03:24:49.181 * <bf> 	{ bf-expansion-factor :         2 }
1:C 05 May 2026 03:24:49.180 * Redis version=8.2.1, bits=64, commit=00000000, modified=1, pid=1, just started
1:M 05 May 2026 03:24:49.181 * <bf> 	{ bf-error-rate       :      0.01 }
1:C 05 May 2026 03:24:49.180 * Configuration loaded
1:M 05 May 2026 03:24:49.181 * <bf> 	{ cf-expansion-factor :         1 }
1:M 05 May 2026 03:24:49.181 * <bf> 	{ cf-max-expansions   :        32 }
1:M 05 May 2026 03:24:49.181 * <bf> ]
1:M 05 May 2026 03:24:49.181 * Module 'bf' loaded from /usr/local/lib/redis/modules//redisbloom.so
1:M 05 May 2026 03:24:49.184 * <search> Redis version found by RedisSearch : 8.2.1 - oss
1:M 05 May 2026 03:24:49.184 * <search> RediSearch version 8.2.1 (Git=dba8dd0)
1:M 05 May 2026 03:24:49.184 * <search> Low level api version 1 initialized successfully
1:M 05 May 2026 03:24:49.184 * <search> gc: ON, prefix min length: 2, min word length to stem: 4, prefix max expansions: 200, query timeout (ms): 500, timeout policy: return, cursor read size: 1000, cursor max idle (ms): 300000, max doctable size: 1000000, max number of search results:  1000000, 
1:M 05 May 2026 03:24:49.184 * <search> Initialized thread pools!
1:M 05 May 2026 03:24:49.184 * <search> Disabled workers threadpool of size 0
1:M 05 May 2026 03:24:49.184 * <search> Subscribe to config changes
1:M 05 May 2026 03:24:49.184 * <search> Enabled role change notification
1:M 05 May 2026 03:24:49.184 * <search> Cluster configuration: AUTO partitions, type: 0, coordinator timeout: 0ms
1:M 05 May 2026 03:24:49.184 * <search> Register write commands
1:M 05 May 2026 03:24:49.185 * Module 'search' loaded from /usr/local/lib/redis/modules//redisearch.so
1:M 05 May 2026 03:24:49.185 * <timeseries> ]
1:M 05 May 2026 03:24:49.185 * <timeseries> Detected redis oss
1:M 05 May 2026 03:24:49.185 * <timeseries> Enabled diskless replication
1:M 05 May 2026 03:24:49.185 * Module 'timeseries' loaded from /usr/local/lib/redis/modules//redistimeseries.so
1:M 05 May 2026 03:24:49.187 * <ReJSON> Created new data type 'ReJSON-RL'
1:M 05 May 2026 03:24:49.185 * <timeseries> RedisTimeSeries version 80200, git_sha=1439d4a439ca9c063e6ef124a510abff09a5d493
1:M 05 May 2026 03:24:49.185 * <timeseries> Redis version found by RedisTimeSeries : 8.2.1 - oss
1:M 05 May 2026 03:24:49.185 * <timeseries> Registering configuration options: [
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-compaction-policy   :              }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-num-threads         :            3 }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-retention-policy    :            0 }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-duplicate-policy    :        block }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-chunk-size-bytes    :         4096 }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-encoding            :   compressed }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-ignore-max-time-diff:            0 }
1:M 05 May 2026 03:24:49.185 * <timeseries> 	{ ts-ignore-max-val-diff :     0.000000 }
1:M 05 May 2026 03:24:49.187 * Server initialized
1:M 05 May 2026 03:24:49.187 * <ReJSON> version: 80200 git sha: unknown branch: unknown
1:M 05 May 2026 03:24:49.187 * <ReJSON> Exported RedisJSON_V4 API
1:M 05 May 2026 03:24:49.187 * Ready to accept connections tcp
1:M 05 May 2026 03:24:49.187 * <ReJSON> Exported RedisJSON_V1 API
1:M 05 May 2026 03:24:49.187 * <ReJSON> Exported RedisJSON_V5 API
1:M 05 May 2026 03:24:49.187 * <ReJSON> Enabled diskless replication
1:M 05 May 2026 03:24:49.187 * <ReJSON> Exported RedisJSON_V2 API
1:M 05 May 2026 03:24:49.187 * <ReJSON> Initialized shared string cache, thread safe: false.
1:M 05 May 2026 03:24:49.187 * <ReJSON> Exported RedisJSON_V3 API
1:M 05 May 2026 03:24:49.187 * Module 'ReJSON' loaded from /usr/local/lib/redis/modules//rejson.so
1:M 05 May 2026 03:24:49.187 * <search> Acquired RedisJSON_V5 API






