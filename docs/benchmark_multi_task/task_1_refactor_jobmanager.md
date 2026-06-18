# Task 1: Refactor JobManager (Semantic)

**Query:** Refactor JobManager: understand how jobs are scheduled and executed
**Symbols:** JobManager, Job
**Search patterns:** JobManager, class Job 
**Golden set (4 files):**
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java`
- `app/src/main/java/org/thoughtcrime/securesms/dependencies/AppDependencies.kt`
- `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java`

## Effort Comparison

| Agent | Turns | Tokens | Files Read | Coverage | Latency |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 10 | 16,669 | 8 | 100.0% | 917ms |
| AST-Index | 34 | 146,296 | 29 | 100.0% | 64ms |
| Graphify | 5 | 17,777 | 4 | 100.0% | 3487ms |
| Vanilla (rg) | 115 | 370,158 | 113 | 100.0% | 144ms |

## Information Relevance

How much of what each agent read was actually useful?

| Agent | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 4 | 4 | 0 | 50.0% | 100.0% |
| AST-Index | 4 | 10 | 15 | 13.8% | 48.3% |
| Graphify | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 4 | 58 | 51 | 3.5% | 54.9% |

- **Golden** = file is in the required golden set
- **Related** = same package or name matches a task symbol
- **Noise** = unrelated file that was read unnecessarily
- **Precision** = golden / total files read
- **Signal%** = (golden + related) / total files read

### RAG+AST — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 2,015 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 726 | ⭐ golden |
| 3 | `app/src/test/java/org/thoughtcrime/securesms/jobs/FastJobStorageTest.kt` | 570 | ✅ related |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RecheckPaymentsMigrationJob.kt` | 112 | ✅ related |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackfillDigestsForDuplicatesMigrationJob.kt` | 132 | ✅ related |
| 6 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/JobManagerPerformanceTests.kt` | 778 | ✅ related |
| 7 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/AppDependencies.kt` | 10,372 | ⭐ golden |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java` | 1,964 | ⭐ golden |

### AST-Index — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 12,986 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 10,232 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/AppDependencies.kt` | 5,186 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java` | 982 | ⭐ golden |
| 5 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/JobManagerPerformanceTests.kt` | 995 | ✅ related |
| 6 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverDependencyProvider.kt` | 755 | ❌ noise |
| 7 | `app/src/benchmark/java/org/thoughtcrime/securesms/BenchmarkApplicationContext.kt` | 687 | ❌ noise |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerAdditionMigrationJob.java` | 699 | ✅ related |
| 9 | `app/src/test/java/org/thoughtcrime/securesms/dependencies/MockApplicationDependencyProvider.kt` | 3,425 | ❌ noise |
| 10 | `app/src/test/java/org/thoughtcrime/securesms/groups/v2/processing/GroupsV2StateProcessorTest.kt` | 12,274 | ❌ noise |
| 11 | `app/src/test/java/org/thoughtcrime/securesms/notifications/MarkReadReceiverTest.kt` | 902 | ❌ noise |
| 12 | `app/src/test/java/org/thoughtcrime/securesms/sms/UploadDependencyGraphTest.kt` | 2,771 | ❌ noise |
| 13 | `app/src/test/java/org/thoughtcrime/securesms/stories/StoriesTest.kt` | 896 | ❌ noise |
| 14 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/AttachmentCompressionJobTest.kt` | 824 | ✅ related |
| 15 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/BackupSubscriptionCheckJobTest.kt` | 5,941 | ✅ related |
| 16 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/InAppPaymentSetupJobTest.kt` | 2,328 | ✅ related |
| 17 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverRule.kt` | 2,317 | ❌ noise |
| 18 | `app/src/benchmarkShared/java/org/signal/benchmark/setup/NoOpJob.kt` | 960 | ✅ related |
| 19 | `app/src/test/java/org/thoughtcrime/securesms/jobmanager/JobControllerTest.kt` | 4,685 | ✅ related |
| 20 | `demo/registration/src/main/java/org/signal/registration/sample/dependencies/FakeDeviceTransferRunner.kt` | 510 | ❌ noise |
| 21 | `demo/video/src/main/java/org/thoughtcrime/video/app/batch/BatchTranscodeViewModel.kt` | 1,940 | ❌ noise |
| 22 | `demo/video/src/main/java/org/thoughtcrime/video/app/transcode/TranscodeTestViewModel.kt` | 1,232 | ❌ noise |
| 23 | `app/src/test/java/org/thoughtcrime/securesms/jobs/JobManagerFactoriesTest.kt` | 199 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationItem.java` | 36,295 | ❌ noise |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/pin/PinRestoreEntryFragment.java` | 2,687 | ❌ noise |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/stickers/manage/StickerManagementRepository.kt` | 1,465 | ❌ noise |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobSchedulerScheduler.java` | 727 | ✅ related |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/database/JobDatabase.kt` | 4,158 | ✅ related |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V149_LegacyMigrations.kt` | 27,238 | ❌ noise |

### Graphify — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 6,493 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 5,116 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/AppDependencies.kt` | 5,186 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java` | 982 | ⭐ golden |

### Vanilla (rg) — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java` | 12,986 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java` | 10,232 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/AppDependencies.kt` | 10,372 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java` | 1,964 | ⭐ golden |
| 5 | `app/src/benchmark/java/org/thoughtcrime/securesms/BenchmarkApplicationContext.kt` | 687 | ❌ noise |
| 6 | `app/src/test/java/org/thoughtcrime/securesms/notifications/MarkReadReceiverTest.kt` | 902 | ❌ noise |
| 7 | `app/src/test/java/org/thoughtcrime/securesms/jobs/JobManagerFactoriesTest.kt` | 199 | ✅ related |
| 8 | `app/src/test/java/org/thoughtcrime/securesms/stories/StoriesTest.kt` | 896 | ❌ noise |
| 9 | `app/src/test/java/org/thoughtcrime/securesms/sms/UploadDependencyGraphTest.kt` | 2,771 | ❌ noise |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationItem.java` | 36,295 | ❌ noise |
| 11 | `app/src/test/java/org/thoughtcrime/securesms/groups/v2/processing/GroupsV2StateProcessorTest.kt` | 12,274 | ❌ noise |
| 12 | `app/src/test/java/org/thoughtcrime/securesms/dependencies/MockApplicationDependencyProvider.kt` | 3,425 | ❌ noise |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/messages/GroupSendUtil.java` | 13,582 | ❌ noise |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/messages/MessageDecryptor.kt` | 8,124 | ❌ noise |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/pin/PinRestoreEntryFragment.java` | 2,687 | ❌ noise |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerLaunchMigrationJob.java` | 600 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/stickers/manage/StickerManagementRepository.kt` | 1,465 | ❌ noise |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageCapabilityMigrationJob.java` | 712 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UpdateSmsJobsMigrationJob.kt` | 801 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ApplicationMigrations.java` | 9,641 | ❌ noise |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobSchedulerScheduler.java` | 727 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageServiceMigrationJob.java` | 604 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManagerExtensions.kt` | 560 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ProfileMigrationJob.java` | 352 | ✅ related |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerAdditionMigrationJob.java` | 699 | ✅ related |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/InAppScheduler.java` | 418 | ✅ related |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AccountRecordMigrationJob.java` | 472 | ✅ related |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/AlarmManagerScheduler.java` | 603 | ✅ related |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/BootReceiver.java` | 119 | ✅ related |
| 30 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 774 | ✅ related |
| 31 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerDayByDayMigrationJob.java` | 360 | ✅ related |
| 32 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 199 | ✅ related |
| 33 | `app/src/main/java/org/thoughtcrime/securesms/migrations/EmojiDownloadMigrationJob.java` | 362 | ✅ related |
| 34 | `app/src/main/java/org/thoughtcrime/securesms/migrations/LegacyMigrationJob.java` | 2,806 | ✅ related |
| 35 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AvatarIdRemovalMigrationJob.java` | 379 | ✅ related |
| 36 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PinOptOutMigration.java` | 567 | ❌ noise |
| 37 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/impl/ChargingAndBatteryIsNotLowConstraintObserver.java` | 646 | ✅ related |
| 38 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AttributesMigrationJob.java` | 416 | ✅ related |
| 39 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerMyDailyLifeMigrationJob.java` | 368 | ✅ related |
| 40 | `app/src/androidTest/java/org/thoughtcrime/securesms/jobs/JobManagerPerformanceTests.kt` | 995 | ✅ related |
| 41 | `app/src/androidTest/java/org/thoughtcrime/securesms/testing/incomingmessageobserver/IncomingMessageObserverDependencyProvider.kt` | 755 | ❌ noise |
| 42 | `app/src/main/java/org/thoughtcrime/securesms/payments/backup/phrase/PaymentsRecoveryPhraseRepository.java` | 520 | ❌ noise |
| 43 | `app/src/main/java/org/thoughtcrime/securesms/mediasend/MediaUploadRepository.java` | 2,334 | ❌ noise |
| 44 | `app/src/main/java/org/thoughtcrime/securesms/payments/preferences/PaymentsActivity.java` | 622 | ❌ noise |
| 45 | `app/src/main/java/org/thoughtcrime/securesms/payments/preferences/PaymentsHomeRepository.java` | 705 | ❌ noise |
| 46 | `app/src/main/java/org/thoughtcrime/securesms/devicetransfer/olddevice/OldDeviceTransferSetupFragment.java` | 1,150 | ❌ noise |
| 47 | `app/src/main/java/org/thoughtcrime/securesms/preferences/BackupsPreferenceFragment.java` | 3,660 | ❌ noise |
| 48 | `app/src/main/java/org/thoughtcrime/securesms/util/SignalUncaughtExceptionHandler.java` | 744 | ❌ noise |
| 49 | `app/src/main/java/org/thoughtcrime/securesms/messagerequests/MessageRequestRepository.java` | 4,696 | ❌ noise |
| 50 | `app/src/main/java/org/thoughtcrime/securesms/contacts/ContactsSyncAdapter.java` | 989 | ❌ noise |
| 51 | `app/src/main/java/org/thoughtcrime/securesms/ApplicationContext.java` | 7,326 | ✅ related |
| 52 | `app/src/main/java/org/thoughtcrime/securesms/sms/UploadDependencyGraph.kt` | 2,276 | ❌ noise |
| 53 | `app/src/main/java/org/thoughtcrime/securesms/sms/MessageSender.java` | 8,979 | ❌ noise |
| 54 | `app/src/main/java/org/thoughtcrime/securesms/messageprocessingalarm/RoutineMessageFetchReceiver.java` | 938 | ❌ noise |
| 55 | `app/src/main/java/org/thoughtcrime/securesms/util/JobExtensions.kt` | 108 | ✅ related |
| 56 | `app/src/main/java/org/thoughtcrime/securesms/contactshare/SharedContactDetailsActivity.java` | 2,367 | ❌ noise |
| 57 | `app/src/main/java/org/thoughtcrime/securesms/conversationlist/ConversationListFragment.java` | 21,914 | ❌ noise |
| 58 | `app/src/main/java/org/thoughtcrime/securesms/logsubmit/LogSectionJobs.java` | 114 | ✅ related |
| 59 | `app/src/main/java/org/thoughtcrime/securesms/recipients/RecipientUtil.java` | 3,966 | ❌ noise |
| 60 | `app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java` | 9,887 | ❌ noise |
| 61 | `app/src/main/java/org/thoughtcrime/securesms/logsubmit/LogSectionConstraints.java` | 286 | ❌ noise |
| 62 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt` | 1,672 | ❌ noise |
| 63 | `app/src/main/java/org/thoughtcrime/securesms/gcm/FcmReceiveService.java` | 1,269 | ❌ noise |
| 64 | `app/src/main/java/org/thoughtcrime/securesms/util/ProfileUtil.java` | 5,575 | ❌ noise |
| 65 | `app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java` | 8,147 | ✅ related |
| 66 | `app/src/main/java/org/thoughtcrime/securesms/wallpaper/WallpaperStorage.java` | 655 | ❌ noise |
| 67 | `app/src/main/java/org/thoughtcrime/securesms/notifications/MarkReadReceiver.java` | 1,540 | ❌ noise |
| 68 | `app/src/main/java/org/thoughtcrime/securesms/apkupdate/ApkUpdateRefreshListener.java` | 402 | ❌ noise |
| 69 | `app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java` | 17,688 | ❌ noise |
| 70 | `app/src/main/java/org/thoughtcrime/securesms/ratelimit/RateLimitUtil.java` | 389 | ❌ noise |
| 71 | `app/src/main/java/org/thoughtcrime/securesms/revealable/ViewOnceMessageRepository.java` | 526 | ❌ noise |
| 72 | `app/src/main/java/org/thoughtcrime/securesms/registration/util/RegistrationUtil.java` | 820 | ❌ noise |
| 73 | `app/src/main/java/org/thoughtcrime/securesms/service/BootReceiver.java` | 116 | ❌ noise |
| 74 | `app/src/main/java/org/thoughtcrime/securesms/service/RotateSenderCertificateListener.java` | 273 | ❌ noise |
| 75 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ProfileUploadJob.java` | 609 | ✅ related |
| 76 | `app/src/main/java/org/thoughtcrime/securesms/components/TypingStatusSender.java` | 770 | ❌ noise |
| 77 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentRecurringContextJob.kt` | 7,318 | ✅ related |
| 78 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ThreadUpdateJob.java` | 699 | ✅ related |
| 79 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceReadUpdateJob.java` | 1,815 | ✅ related |
| 80 | `app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJob.kt` | 4,949 | ✅ related |
| 81 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StickerPackDownloadJob.java` | 2,178 | ✅ related |
| 82 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendRetryReceiptJob.java` | 1,364 | ✅ related |
| 83 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushSendJob.kt` | 5,516 | ✅ related |
| 84 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RemoteDeleteSendJob.java` | 3,433 | ✅ related |
| 85 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RetrieveProfileAvatarJob.java` | 2,312 | ✅ related |
| 86 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushDistributionListSendJob.java` | 2,993 | ✅ related |
| 87 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentOneTimeContextJob.kt` | 3,495 | ✅ related |
| 88 | `app/src/main/java/org/thoughtcrime/securesms/profiles/spoofing/ReviewCardRepository.java` | 1,245 | ❌ noise |
| 89 | `app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentPurchaseTokenJob.kt` | 2,126 | ✅ related |
| 90 | `app/src/main/java/org/thoughtcrime/securesms/jobs/MultiDeviceViewedUpdateJob.java` | 1,727 | ✅ related |
| 91 | `app/src/main/java/org/thoughtcrime/securesms/jobs/RequestGroupV2InfoJob.java` | 771 | ✅ related |
| 92 | `app/src/main/java/org/thoughtcrime/securesms/profiles/manage/EditProfileViewModel.java` | 2,546 | ❌ noise |
| 93 | `app/src/main/java/org/thoughtcrime/securesms/profiles/manage/EditProfileRepository.java` | 912 | ❌ noise |
| 94 | `app/src/main/java/org/thoughtcrime/securesms/components/voice/VoiceNotePlaybackService.java` | 3,777 | ❌ noise |
| 95 | `app/src/main/java/org/thoughtcrime/securesms/jobs/FcmRefreshJob.java` | 1,657 | ✅ related |
| 96 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PushGroupSendJob.java` | 8,406 | ✅ related |
| 97 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendReadReceiptJob.java` | 2,732 | ✅ related |
| 98 | `app/src/main/java/org/thoughtcrime/securesms/jobs/TrimThreadJob.java` | 985 | ✅ related |
| 99 | `app/src/main/java/org/thoughtcrime/securesms/jobs/DownloadLatestEmojiDataJob.java` | 3,593 | ✅ related |
| 100 | `app/src/main/java/org/thoughtcrime/securesms/jobs/LocalBackupJob.java` | 2,520 | ✅ related |
| 101 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ConversationShortcutUpdateJob.java` | 884 | ✅ related |
| 102 | `app/src/main/java/org/thoughtcrime/securesms/profiles/edit/EditSelfProfileRepository.java` | 1,455 | ❌ noise |
| 103 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupV2UpdateSelfProfileKeyJob.java` | 2,180 | ✅ related |
| 104 | `app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java` | 904 | ✅ related |
| 105 | `app/src/main/java/org/thoughtcrime/securesms/jobs/SendViewedReceiptJob.java` | 2,931 | ✅ related |
| 106 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AvatarGroupsV2DownloadJob.java` | 1,911 | ✅ related |
| 107 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ✅ related |
| 108 | `app/src/main/java/org/thoughtcrime/securesms/jobs/EmojiSearchIndexDownloadJob.java` | 1,901 | ✅ related |
| 109 | `app/src/main/java/org/thoughtcrime/securesms/jobs/PaymentSendJob.java` | 2,774 | ✅ related |
| 110 | `app/src/main/java/org/thoughtcrime/securesms/jobs/GroupCallPeekJob.java` | 647 | ✅ related |
| 111 | `app/src/main/java/org/thoughtcrime/securesms/jobs/ForceUpdateGroupV2Job.java` | 754 | ✅ related |
| 112 | `app/src/main/java/org/thoughtcrime/securesms/service/DirectoryRefreshListener.java` | 378 | ❌ noise |
| 113 | `app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java` | 15,909 | ❌ noise |

## Analysis

- **Most token-efficient:** RAG+AST (16,669 tokens)
- **Highest precision:** Graphify (100.0% golden)
- **Highest signal%:** RAG+AST (100.0% golden+related)
- **Most noise:** Vanilla (rg) (51 irrelevant files read)
