# Task 5: Blast Radius: Job Base Class (Graph)

**Query:** If I change the Job base class, what code is affected? Show Job subclasses and the job manager
**Symbols:** BaseJob, Job, JobManager, CoroutineJob
**Search patterns:** extends BaseJob, : BaseJob, extends Job 
**Golden set (4 files):**
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/CoroutineJob.kt`

## Effort Comparison

| Agent | Turns | Tokens | Files Read | Coverage | Latency |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 5 | 2,473 | 4 | 100.0% | 56ms |
| AST-Index | 90 | 186,427 | 81 | 100.0% | 152ms |
| Graphify | 5 | 12,638 | 4 | 100.0% | 2534ms |
| Vanilla (rg) | 126 | 235,180 | 123 | 100.0% | 212ms |

## Information Relevance

How much of what each agent read was actually useful?

| Agent | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 4 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 4 | 66 | 11 | 4.9% | 86.4% |
| Graphify | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 4 | 119 | 0 | 3.3% | 100.0% |

- **Golden** = file is in the required golden set
- **Related** = same package or name matches a task symbol
- **Noise** = unrelated file that was read unnecessarily
- **Precision** = golden / total files read
- **Signal%** = (golden + related) / total files read

### RAG+AST — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 931 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java` | 735 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 726 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/CoroutineJob.kt` | 81 | ⭐ golden |

### AST-Index — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 10,232 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 12,986 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java` | 1,808 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/CoroutineJob.kt` | 250 | ⭐ golden |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AvatarGroupsV1DownloadJob.java` | 1,305 | ✅ related |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CheckServiceReachabilityJob.kt` | 1,067 | ✅ related |
| 7 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallUpdateSendJob.java` | 2,602 | ✅ related |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LocalBackupJobApi29.java` | 2,773 | ✅ related |
| 9 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceBlockedUpdateJob.kt` | 747 | ✅ related |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceContactUpdateJob.java` | 4,531 | ✅ related |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStickerPackSyncJob.java` | 984 | ✅ related |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/jobs/NullMessageSendJob.java` | 957 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshSvrCredentialsJob.kt` | 599 | ✅ related |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RemoteDeleteSendJob.java` | 3,433 | ✅ related |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoWorkerJob.java` | 1,102 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ResendMessageJob.java` | 2,916 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RetrieveProfileAvatarJob.java` | 2,312 | ✅ related |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendRetryReceiptJob.java` | 1,364 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SenderKeyDistributionSendJob.java` | 1,881 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ServiceOutageDetectionJob.java` | 872 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StickerPackDownloadJob.java` | 2,178 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SubmitRateLimitPushChallengeJob.java` | 667 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/jobs/TrimThreadJob.java` | 985 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationCompleteJob.java` | 567 | ✅ related |
| 25 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/AttachmentCompressionJobTest.kt` | 824 | ✅ related |
| 26 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/BackupSubscriptionCheckJobTest.kt` | 5,941 | ✅ related |
| 27 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/InAppPaymentSetupJobTest.kt` | 2,328 | ✅ related |
| 28 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/JobManagerPerformanceTests.kt` | 995 | ✅ related |
| 29 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverRule.kt` | 2,317 | ❌ noise |
| 30 | `app/src/benchmarkShared/java/org/signal/benchmark/setup/NoOpJob.kt` | 960 | ✅ related |
| 31 | `app/src/test/java/org/thoughtcrime/securesms/jobmanager/JobControllerTest.kt` | 4,685 | ✅ related |
| 32 | `demo/registration/src/main/java/org/signal/registration/sample/dependencies/FakeDeviceTransferRunner.kt` | 510 | ❌ noise |
| 33 | `demo/video/src/main/java/org/thoughtcrime/video/app/batch/BatchTranscodeViewModel.kt` | 1,940 | ❌ noise |
| 34 | `demo/video/src/main/java/org/thoughtcrime/video/app/transcode/TranscodeTestViewModel.kt` | 1,232 | ❌ noise |
| 35 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverDependencyProvider.kt` | 755 | ❌ noise |
| 36 | `app/src/benchmark/java/org/thoughtcrime/securesms/BenchmarkApplicationContext.kt` | 687 | ❌ noise |
| 37 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerAdditionMigrationJob.java` | 699 | ✅ related |
| 38 | `app/src/test/java/org/thoughtcrime/securesms/dependencies/MockApplicationDependencyProvider.kt` | 3,425 | ❌ noise |
| 39 | `app/src/test/java/org/thoughtcrime/securesms/groups/v2/processing/GroupsV2StateProcessorTest.kt` | 12,274 | ❌ noise |
| 40 | `app/src/test/java/org/thoughtcrime/securesms/notifications/MarkReadReceiverTest.kt` | 902 | ❌ noise |
| 41 | `app/src/test/java/org/thoughtcrime/securesms/sms/UploadDependencyGraphTest.kt` | 2,771 | ❌ noise |
| 42 | `app/src/test/java/org/thoughtcrime/securesms/stories/StoriesTest.kt` | 896 | ❌ noise |
| 43 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BackupSubscriptionCheckJob.kt` | 3,842 | ✅ related |
| 44 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CheckKeyTransparencyJob.kt` | 2,041 | ✅ related |
| 45 | `app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJobV2.kt` | 6,020 | ✅ related |
| 46 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PostRegistrationBackupRedemptionJob.kt` | 1,513 | ✅ related |
| 47 | `app/src/test/java/org/thoughtcrime/securesms/jobs/PreKeysSyncJobTest.kt` | 2,226 | ✅ related |
| 48 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupRingCleanupJob.kt` | 417 | ✅ related |
| 49 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ProfileUploadJob.java` | 609 | ✅ related |
| 50 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallSyncEventJob.kt` | 2,136 | ✅ related |
| 51 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceMessageRequestResponseJob.java` | 1,946 | ✅ related |
| 52 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentNotificationSendJobV2.kt` | 756 | ✅ related |
| 53 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StoryOnboardingDownloadJob.kt` | 1,785 | ✅ related |
| 54 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ReportSpamJob.java` | 1,321 | ✅ related |
| 55 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentRecurringContextJob.kt` | 7,318 | ✅ related |
| 56 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ThreadUpdateJob.java` | 699 | ✅ related |
| 57 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RestoreAttachmentJob.kt` | 6,058 | ✅ related |
| 58 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AttachmentUploadJob.kt` | 4,084 | ✅ related |
| 59 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushGroupSilentUpdateSendJob.java` | 2,628 | ✅ related |
| 60 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceReadUpdateJob.java` | 1,815 | ✅ related |
| 61 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushSendJob.kt` | 5,516 | ✅ related |
| 62 | `app/src/main/java/org/thoughtcrime/securesms/jobs/TypingSendJob.java` | 1,376 | ✅ related |
| 63 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceKeysUpdateJob.kt` | 685 | ✅ related |
| 64 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentOneTimeContextJob.kt` | 3,495 | ✅ related |
| 65 | `app/src/main/java/org/thoughtcrime/securesms/jobs/DirectoryRefreshJob.java` | 864 | ✅ related |
| 66 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BackupRestoreMediaJob.kt` | 1,522 | ✅ related |
| 67 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStorageSyncRequestJob.java` | 732 | ✅ related |
| 68 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RotateCertificateJob.java` | 830 | ✅ related |
| 69 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStorySendSyncJob.kt` | 1,007 | ✅ related |
| 70 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CleanPreKeysJob.java` | 459 | ✅ related |
| 71 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RebuildMessageSearchIndexJob.kt` | 471 | ✅ related |
| 72 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CreateReleaseChannelJob.kt` | 1,140 | ✅ related |
| 73 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendPaymentsActivatedJob.kt` | 567 | ✅ related |
| 74 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceProfileKeyUpdateJob.java` | 1,453 | ✅ related |
| 75 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendReadReceiptJob.java` | 2,732 | ✅ related |
| 76 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StorageSyncJob.kt` | 8,029 | ✅ related |
| 77 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStickerPackOperationJob.java` | 1,243 | ✅ related |
| 78 | `app/src/main/java/org/thoughtcrime/securesms/jobs/OptimizeMessageSearchIndexJob.kt` | 651 | ✅ related |
| 79 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentLedgerUpdateJob.java` | 1,020 | ✅ related |
| 80 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentTransactionCheckJob.java` | 1,491 | ✅ related |
| 81 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GenerateAudioWaveFormJob.kt` | 671 | ✅ related |

### Graphify — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 5,116 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 6,493 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java` | 904 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/CoroutineJob.kt` | 125 | ⭐ golden |

### Vanilla (rg) — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 5,116 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 6,493 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java` | 1,808 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/CoroutineJob.kt` | 125 | ⭐ golden |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationCompleteJob.java` | 567 | ✅ related |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SubmitRateLimitPushChallengeJob.java` | 667 | ✅ related |
| 7 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendRetryReceiptJob.java` | 1,364 | ✅ related |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/jobs/TrimThreadJob.java` | 985 | ✅ related |
| 9 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ProfileUploadJob.java` | 609 | ✅ related |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LocalBackupJobApi29.java` | 2,773 | ✅ related |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallUpdateSendJob.java` | 2,602 | ✅ related |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RemoteDeleteSendJob.java` | 3,433 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SenderKeyDistributionSendJob.java` | 1,881 | ✅ related |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoWorkerJob.java` | 1,102 | ✅ related |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RetrieveProfileAvatarJob.java` | 2,312 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/jobs/NullMessageSendJob.java` | 957 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceContactUpdateJob.java` | 4,531 | ✅ related |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStickerPackOperationJob.java` | 1,243 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StickerPackDownloadJob.java` | 2,178 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ServiceOutageDetectionJob.java` | 872 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStickerPackSyncJob.java` | 984 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceMessageRequestResponseJob.java` | 1,946 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceProfileKeyUpdateJob.java` | 1,453 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ConversationShortcutUpdateJob.java` | 884 | ✅ related |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceVerifiedUpdateJob.java` | 1,731 | ✅ related |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendReadReceiptJob.java` | 2,732 | ✅ related |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentSendJob.java` | 2,774 | ✅ related |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AvatarGroupsV1DownloadJob.java` | 1,305 | ✅ related |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AvatarGroupsV2DownloadJob.java` | 1,911 | ✅ related |
| 30 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshAttributesJob.java` | 1,645 | ✅ related |
| 31 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceViewedUpdateJob.java` | 1,727 | ✅ related |
| 32 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceViewOnceOpenJob.java` | 1,352 | ✅ related |
| 33 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MarkerJob.java` | 351 | ✅ related |
| 34 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentNotificationSendJob.java` | 1,556 | ✅ related |
| 35 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallPeekJob.java` | 647 | ✅ related |
| 36 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RotateProfileKeyJob.java` | 420 | ✅ related |
| 37 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ReportSpamJob.java` | 1,321 | ✅ related |
| 38 | `app/src/main/java/org/thoughtcrime/securesms/jobs/DownloadLatestEmojiDataJob.java` | 3,593 | ✅ related |
| 39 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendViewedReceiptJob.java` | 2,931 | ✅ related |
| 40 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AutomaticSessionResetJob.java` | 1,919 | ✅ related |
| 41 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceConfigurationUpdateJob.java` | 1,626 | ✅ related |
| 42 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoJob.java` | 771 | ✅ related |
| 43 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ForceUpdateGroupV2Job.java` | 754 | ✅ related |
| 44 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AttachmentCompressionJob.java` | 5,008 | ✅ related |
| 45 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StickerDownloadJob.java` | 1,476 | ✅ related |
| 46 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LocalBackupJob.java` | 2,520 | ✅ related |
| 47 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ResendMessageJob.java` | 2,916 | ✅ related |
| 48 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendDeliveryReceiptJob.java` | 1,966 | ✅ related |
| 49 | `app/src/main/java/org/thoughtcrime/securesms/jobs/EmojiSearchIndexDownloadJob.java` | 1,901 | ✅ related |
| 50 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AttachmentCopyJob.java` | 947 | ✅ related |
| 51 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ThreadUpdateJob.java` | 699 | ✅ related |
| 52 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupV2UpdateSelfProfileKeyJob.java` | 2,180 | ✅ related |
| 53 | `app/src/main/java/org/thoughtcrime/securesms/jobs/TypingSendJob.java` | 1,376 | ✅ related |
| 54 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceProfileContentUpdateJob.java` | 735 | ✅ related |
| 55 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceOutgoingPaymentSyncJob.java` | 1,429 | ✅ related |
| 56 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentLedgerUpdateJob.java` | 1,020 | ✅ related |
| 57 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentTransactionCheckJob.java` | 1,491 | ✅ related |
| 58 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushGroupSilentUpdateSendJob.java` | 2,628 | ✅ related |
| 59 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStorageSyncRequestJob.java` | 732 | ✅ related |
| 60 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ProfileKeySendJob.java` | 2,563 | ✅ related |
| 61 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallPeekWorkerJob.java` | 745 | ✅ related |
| 62 | `app/src/main/java/org/thoughtcrime/securesms/jobs/DirectoryRefreshJob.java` | 864 | ✅ related |
| 63 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java` | 1,272 | ✅ related |
| 64 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceReadUpdateJob.java` | 1,815 | ✅ related |
| 65 | `app/src/main/java/org/thoughtcrime/securesms/jobs/FcmRefreshJob.java` | 1,657 | ✅ related |
| 66 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ForceUpdateGroupV2WorkerJob.java` | 964 | ✅ related |
| 67 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RotateCertificateJob.java` | 830 | ✅ related |
| 68 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ReactionSendJob.java` | 3,947 | ✅ related |
| 69 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CleanPreKeysJob.java` | 459 | ✅ related |
| 70 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupRingCleanupJob.kt` | 417 | ✅ related |
| 71 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallSyncEventJob.kt` | 2,136 | ✅ related |
| 72 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentNotificationSendJobV2.kt` | 756 | ✅ related |
| 73 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StoryOnboardingDownloadJob.kt` | 1,785 | ✅ related |
| 74 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentRecurringContextJob.kt` | 7,318 | ✅ related |
| 75 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RestoreAttachmentJob.kt` | 6,058 | ✅ related |
| 76 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AttachmentUploadJob.kt` | 4,084 | ✅ related |
| 77 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushSendJob.kt` | 5,516 | ✅ related |
| 78 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceKeysUpdateJob.kt` | 685 | ✅ related |
| 79 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentOneTimeContextJob.kt` | 3,495 | ✅ related |
| 80 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BackupRestoreMediaJob.kt` | 1,522 | ✅ related |
| 81 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceStorySendSyncJob.kt` | 1,007 | ✅ related |
| 82 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RebuildMessageSearchIndexJob.kt` | 471 | ✅ related |
| 83 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RestoreAttachmentThumbnailJob.kt` | 1,753 | ✅ related |
| 84 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LeaveGroupV2WorkerJob.kt` | 696 | ✅ related |
| 85 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ApkUpdateJob.kt` | 2,423 | ✅ related |
| 86 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshDonationSubscriptionStatusJob.kt` | 894 | ✅ related |
| 87 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentAuthCheckJob.kt` | 3,617 | ✅ related |
| 88 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PreKeysSyncJob.kt` | 4,377 | ✅ related |
| 89 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessEarlyMessagesJob.kt` | 848 | ✅ related |
| 90 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentKeepAliveJob.kt` | 4,551 | ✅ related |
| 91 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RetrieveRemoteAnnouncementsJob.kt` | 4,998 | ✅ related |
| 92 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallLinkPeekJob.kt` | 630 | ✅ related |
| 93 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallLinkUpdateSendJob.kt` | 893 | ✅ related |
| 94 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentRedemptionJob.kt` | 2,825 | ✅ related |
| 95 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CallLogEventSendJob.kt` | 1,047 | ✅ related |
| 96 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceCallLinkSyncJob.kt` | 667 | ✅ related |
| 97 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SyncSystemContactLinksJob.kt` | 1,207 | ✅ related |
| 98 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceBlockedUpdateJob.kt` | 747 | ✅ related |
| 99 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StorageAccountRestoreJob.kt` | 1,645 | ✅ related |
| 100 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshOwnProfileJob.kt` | 5,098 | ✅ related |
| 101 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ConversationShortcutRankingUpdateJob.kt` | 888 | ✅ related |
| 102 | `app/src/main/java/org/thoughtcrime/securesms/jobs/FontDownloaderJob.kt` | 649 | ✅ related |
| 103 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshSvrCredentialsJob.kt` | 599 | ✅ related |
| 104 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RefreshCallLinkDetailsJob.kt` | 609 | ✅ related |
| 105 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceContactSyncJob.kt` | 1,361 | ✅ related |
| 106 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CheckServiceReachabilityJob.kt` | 1,067 | ✅ related |
| 107 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentGiftSendJob.kt` | 1,593 | ✅ related |
| 108 | `app/src/main/java/org/thoughtcrime/securesms/jobs/FetchRemoteMegaphoneImageJob.kt` | 685 | ✅ related |
| 109 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StorageForcePushJob.kt` | 2,358 | ✅ related |
| 110 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AttachmentDownloadJob.kt` | 5,196 | ✅ related |
| 111 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RetrieveProfileJob.kt` | 6,761 | ✅ related |
| 112 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LeaveGroupV2Job.kt` | 475 | ✅ related |
| 113 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GenerateAudioWaveFormJob.kt` | 671 | ✅ related |
| 114 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AccountConsistencyWorkerJob.kt` | 940 | ✅ related |
| 115 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceSubscriptionSyncRequestJob.kt` | 634 | ✅ related |
| 116 | `app/src/main/java/org/thoughtcrime/securesms/jobs/OptimizeMessageSearchIndexJob.kt` | 651 | ✅ related |
| 117 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageErrorJob.kt` | 1,012 | ✅ related |
| 118 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushProcessMessageJob.kt` | 1,988 | ✅ related |
| 119 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StorageSyncJob.kt` | 8,029 | ✅ related |
| 120 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendPaymentsActivatedJob.kt` | 567 | ✅ related |
| 121 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CreateReleaseChannelJob.kt` | 1,140 | ✅ related |
| 122 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 774 | ✅ related |
| 123 | `app/src/main/java/org/thoughtcrime/securesms/jobs/FailingJob.java` | 276 | ✅ related |

## Analysis

- **Most token-efficient:** RAG+AST (2,473 tokens)
- **Highest precision:** RAG+AST (100.0% golden)
- **Highest signal%:** RAG+AST (100.0% golden+related)
- **Most noise:** AST-Index (11 irrelevant files read)
