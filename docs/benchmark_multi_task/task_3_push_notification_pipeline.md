# Task 3: Push Notification Pipeline (Flow)

**Query:** Trace how Signal receives and processes push notifications from FCM to message decryption
**Symbols:** FcmFetchManager, PushProcessMessageJob, MessageFetchJob
**Search patterns:** FcmFetchManager, PushProcessMessageJob, MessageFetchJob
**Golden set (4 files):**
- `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt`
- `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt`
- `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java`
- `app/src/main/java/org/thoughtcrime/securesms/messages/IncomingMessageObserver.kt`

## Effort Comparison

| Agent | Turns | Tokens | Files Read | Coverage | Latency |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 6 | 15,586 | 4 | 100.0% | 688ms |
| AST-Index | 33 | 87,205 | 26 | 100.0% | 138ms |
| Graphify | 5 | 11,984 | 4 | 100.0% | 2559ms |
| Vanilla (rg) | 31 | 89,635 | 28 | 100.0% | 183ms |

## Information Relevance

How much of what each agent read was actually useful?

| Agent | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 4 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 4 | 15 | 7 | 15.4% | 73.1% |
| Graphify | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 4 | 17 | 7 | 14.3% | 75.0% |

- **Golden** = file is in the required golden set
- **Related** = same package or name matches a task symbol
- **Noise** = unrelated file that was read unnecessarily
- **Precision** = golden / total files read
- **Signal%** = (golden + related) / total files read

### RAG+AST — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt` | 867 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java` | 597 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt` | 18 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/messages/IncomingMessageObserver.kt` | 14,104 | ⭐ golden |

### AST-Index — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt` | 3,344 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt` | 3,976 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java` | 2,544 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/messages/IncomingMessageObserver.kt` | 14,104 | ⭐ golden |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/ApplicationContext.java` | 7,326 | ❌ noise |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchForegroundService.kt` | 1,431 | ✅ related |
| 7 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmJobService.java` | 557 | ✅ related |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmReceiveService.java` | 1,269 | ✅ related |
| 9 | `fast-lint/src/test/kotlin/org/signal/fastlint/rules/ForegroundServiceRuleTest.kt` | 380 | ❌ noise |
| 10 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverRule.kt` | 2,317 | ❌ noise |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java` | 8,147 | ❌ noise |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AutomaticSessionResetJob.java` | 1,919 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallLinkPeekJob.kt` | 630 | ✅ related |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ForceUpdateGroupV2WorkerJob.java` | 964 | ✅ related |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallPeekWorkerJob.java` | 745 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LeaveGroupV2WorkerJob.kt` | 696 | ✅ related |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessEarlyMessagesJob.kt` | 848 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageErrorJob.kt` | 1,012 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoWorkerJob.java` | 1,102 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/messages/DataMessageProcessor.kt` | 19,635 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/messages/WebSocketDrainer.kt` | 1,801 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/messageprocessingalarm/RoutineMessageFetchReceiver.java` | 938 | ❌ noise |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/service/BootReceiver.java` | 116 | ❌ noise |
| 25 | `fast-lint/src/main/kotlin/org/signal/fastlint/rules/ForegroundServiceRule.kt` | 579 | ❌ noise |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchBackgroundService.java` | 192 | ✅ related |

### Graphify — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt` | 1,672 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt` | 1,988 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java` | 1,272 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/messages/IncomingMessageObserver.kt` | 7,052 | ⭐ golden |

### Vanilla (rg) — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt` | 3,344 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt` | 3,976 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java` | 2,544 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/messages/IncomingMessageObserver.kt` | 14,104 | ⭐ golden |
| 5 | `fast-lint/src/main/kotlin/org/signal/fastlint/rules/ForegroundServiceRule.kt` | 579 | ❌ noise |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/ApplicationContext.java` | 7,326 | ❌ noise |
| 7 | `fast-lint/src/test/kotlin/org/signal/fastlint/rules/ForegroundServiceRuleTest.kt` | 380 | ❌ noise |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchForegroundService.kt` | 1,431 | ✅ related |
| 9 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmJobService.java` | 557 | ✅ related |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchBackgroundService.java` | 192 | ✅ related |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmReceiveService.java` | 1,269 | ✅ related |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/messages/WebSocketDrainer.kt` | 1,801 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/messages/BatchCache.kt` | 1,442 | ✅ related |
| 14 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverRule.kt` | 2,317 | ❌ noise |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/messages/DataMessageProcessor.kt` | 19,635 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 988 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java` | 8,147 | ❌ noise |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LeaveGroupV2WorkerJob.kt` | 696 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessEarlyMessagesJob.kt` | 848 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallLinkPeekJob.kt` | 630 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallPeekWorkerJob.java` | 745 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ForceUpdateGroupV2WorkerJob.java` | 964 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageErrorJob.kt` | 1,012 | ✅ related |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AutomaticSessionResetJob.java` | 1,919 | ✅ related |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoWorkerJob.java` | 1,102 | ✅ related |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/service/BootReceiver.java` | 116 | ❌ noise |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/messageprocessingalarm/RoutineMessageFetchReceiver.java` | 938 | ❌ noise |

## Analysis

- **Most token-efficient:** Graphify (11,984 tokens)
- **Highest precision:** RAG+AST (100.0% golden)
- **Highest signal%:** RAG+AST (100.0% golden+related)
- **Most noise:** AST-Index (7 irrelevant files read)
