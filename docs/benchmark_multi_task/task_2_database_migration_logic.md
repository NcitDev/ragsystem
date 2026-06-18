# Task 2: Database Migration Logic (Symbol)

**Query:** Find database migration infrastructure and a specific migration
**Symbols:** SignalDatabaseMigration, MigrationJob, JobMigration
**Search patterns:** SignalDatabaseMigration, MigrationJob
**Golden set (3 files):**
- `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/SignalDatabaseMigration.kt`
- `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt`

## Effort Comparison

| Agent | Turns | Tokens | Files Read | Coverage | Latency |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 4 | 1,300 | 3 | 100.0% | 47ms |
| AST-Index | 88 | 80,801 | 81 | 100.0% | 104ms |
| Graphify | 4 | 1,471 | 3 | 100.0% | 2437ms |
| Vanilla (rg) | 264 | 230,501 | 262 | 100.0% | 143ms |

## Information Relevance

How much of what each agent read was actually useful?

| Agent | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 3 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 3 | 67 | 11 | 3.7% | 86.4% |
| Graphify | 3 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 3 | 246 | 13 | 1.1% | 95.0% |

- **Golden** = file is in the required golden set
- **Related** = same package or name matches a task symbol
- **Noise** = unrelated file that was read unnecessarily
- **Precision** = golden / total files read
- **Signal%** = (golden + related) / total files read

### RAG+AST — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 653 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt` | 534 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/SignalDatabaseMigration.kt` | 113 | ⭐ golden |

### AST-Index — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/SignalDatabaseMigration.kt` | 302 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 1,548 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt` | 1,092 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/SignalDatabaseMigrations.kt` | 6,582 | ✅ related |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V194_KyberPreKeyMigration.kt` | 244 | ✅ related |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V195_GroupMemberForeignKeyMigration.kt` | 738 | ✅ related |
| 7 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V199_AddThreadActiveColumn.kt` | 357 | ✅ related |
| 8 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V207_AddChunkSizeColumn.kt` | 138 | ✅ related |
| 9 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V219_PniPreKeyStores.kt` | 238 | ✅ related |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V222_DataHashRefactor.kt` | 240 | ✅ related |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V223_AddNicknameAndNoteFieldsToRecipientTable.kt` | 222 | ✅ related |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V232_CreateInAppPaymentTable.kt` | 319 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V237_ResetGroupForceUpdateTimestamps.kt` | 150 | ✅ related |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V258_FixGroupRevokedInviteeUpdate.kt` | 959 | ✅ related |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V266_UniqueThreadPinOrder.kt` | 1,326 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V267_FixGroupInvitationDeclinedUpdate.kt` | 712 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V268_FixInAppPaymentsErrorStateConsistency.kt` | 540 | ✅ related |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V287_FixInvalidArchiveState.kt` | 167 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V288_CopyStickerDataHashStartToEnd.kt` | 186 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V304_CallAndReplyNotificationSettings.kt` | 159 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V314_FixMessageRequestAcceptedToRecipient.kt` | 168 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V316_AddVerifiedGroupNameHashMigration.kt` | 110 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V321_AddScheduledMessageIndex.kt` | 131 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AttributesMigrationJob.java` | 416 | ✅ related |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AvatarIdRemovalMigrationJob.java` | 379 | ✅ related |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackfillCollapsedEventsMigrationJob.kt` | 277 | ✅ related |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackupJitterMigrationJob.kt` | 370 | ✅ related |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BlobStorageLocationMigrationJob.java` | 523 | ✅ related |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ContactLinkRebuildMigrationJob.kt` | 681 | ✅ related |
| 30 | `app/src/main/java/org/thoughtcrime/securesms/migrations/EmojiSearchEnglishLabelsMigrationJob.kt` | 346 | ✅ related |
| 31 | `app/src/main/java/org/thoughtcrime/securesms/migrations/FixChangeNumberErrorMigrationJob.kt` | 691 | ✅ related |
| 32 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PinOptOutMigration.java` | 567 | ✅ related |
| 33 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PniAccountInitializationMigrationJob.java` | 994 | ✅ related |
| 34 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ProfileSharingUpdateMigrationJob.java` | 376 | ✅ related |
| 35 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RebuildMessageSearchIndexMigrationJob.kt` | 380 | ✅ related |
| 36 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ReleaseChannelRecipientFixMigrationJob.kt` | 307 | ✅ related |
| 37 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerMyDailyLifeMigrationJob.java` | 368 | ✅ related |
| 38 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SubscriberIdMigrationJob.kt` | 487 | ✅ related |
| 39 | `app/src/main/java/org/thoughtcrime/securesms/migrations/Svr2MirrorMigrationJob.kt` | 255 | ✅ related |
| 40 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SyncDistributionListsMigrationJob.java` | 717 | ✅ related |
| 41 | `app/src/main/java/org/thoughtcrime/securesms/migrations/TrimByLengthSettingsMigrationJob.java` | 547 | ✅ related |
| 42 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UserNotificationMigrationJob.java` | 1,387 | ✅ related |
| 43 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UuidMigrationJob.java` | 713 | ✅ related |
| 44 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigrator.java` | 767 | ✅ related |
| 45 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt` | 106 | ✅ related |
| 46 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DonationReceiptRedemptionJobMigration.kt` | 132 | ✅ related |
| 47 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/GroupCallPeekJobDataMigration.kt` | 326 | ❌ noise |
| 48 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 199 | ❌ noise |
| 49 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 988 | ✅ related |
| 50 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/RetrieveProfileJobMigration.java` | 311 | ✅ related |
| 51 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/SendReadReceiptsJobMigration.java` | 398 | ✅ related |
| 52 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/SenderKeyDistributionSendJobRecipientMigration.java` | 597 | ❌ noise |
| 53 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ❌ noise |
| 54 | `app/src/test/java/org/thoughtcrime/securesms/jobmanager/JobMigratorTest.kt` | 962 | ❌ noise |
| 55 | `app/src/test/java/org/thoughtcrime/securesms/jobmanager/migrations/GroupCallPeekJobDataMigrationTest.kt` | 837 | ❌ noise |
| 56 | `app/src/test/java/org/thoughtcrime/securesms/testutil/SignalDatabaseMigrationRule.kt` | 9,265 | ✅ related |
| 57 | `app/src/main/java/org/thoughtcrime/securesms/database/SignalDatabase.kt` | 5,362 | ❌ noise |
| 58 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V220_PreKeyConstraints.kt` | 822 | ✅ related |
| 59 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V151_MyStoryMigration.kt` | 1,075 | ✅ related |
| 60 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V226_AddAttachmentMediaIdIndex.kt` | 148 | ✅ related |
| 61 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V196_BackCallLinksWithRecipientV2.kt` | 879 | ✅ related |
| 62 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V162_ThreadUnreadSelfMentionCountFixup.kt` | 340 | ✅ related |
| 63 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V215_RemoveAttachmentUniqueId.kt` | 886 | ✅ related |
| 64 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V171_ThreadForeignKeyFix.kt` | 1,417 | ✅ related |
| 65 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V238_AddGroupSendEndorsementsColumns.kt` | 182 | ✅ related |
| 66 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V174_ReactionForeignKeyMigration.kt` | 368 | ✅ related |
| 67 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V228_AddNameCollisionTables.kt` | 341 | ✅ related |
| 68 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V166_ThreadAndMessageForeignKeys.kt` | 4,055 | ✅ related |
| 69 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V234_ThumbnailRestoreStateColumn.kt` | 144 | ✅ related |
| 70 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V200_ResetPniColumn.kt` | 162 | ✅ related |
| 71 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V153_MyStoryMigration.kt` | 1,075 | ✅ related |
| 72 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V204_GroupForeignKeyMigration.kt` | 1,026 | ✅ related |
| 73 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V216_PhoneNumberDiscoverable.kt` | 128 | ✅ related |
| 74 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V288_CopyStickerDataHashStartToEndTest.kt` | 2,842 | ❌ noise |
| 75 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V184_CallLinkReplaceIndexMigration.kt` | 453 | ✅ related |
| 76 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V309_GroupTerminatedColumnMigration.kt` | 143 | ✅ related |
| 77 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V287_FixInvalidArchiveStateTest.kt` | 2,465 | ❌ noise |
| 78 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V298_DoNotBackupReleaseNotesTest.kt` | 1,586 | ❌ noise |
| 79 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V288_AddQuoteTargetContentTypeColumnTest.kt` | 1,669 | ❌ noise |
| 80 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V301_RemoveCallLinkEpoch.kt` | 177 | ✅ related |
| 81 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V300_AddKeyTransparencyColumn.kt` | 126 | ✅ related |

### Graphify — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/SignalDatabaseMigration.kt` | 151 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 774 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt` | 546 | ⭐ golden |

### Vanilla (rg) — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/SignalDatabaseMigration.kt` | 302 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationJob.java` | 1,548 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt` | 546 | ⭐ golden |
| 4 | `app/src/test/java/org/thoughtcrime/securesms/testutil/SignalDatabaseMigrationRule.kt` | 9,265 | ✅ related |
| 5 | `app/src/main/java/org/thoughtcrime/securesms/logsubmit/LogSectionDatabaseSchema.kt` | 455 | ❌ noise |
| 6 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V288_CopyStickerDataHashStartToEndTest.kt` | 2,842 | ❌ noise |
| 7 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V288_AddQuoteTargetContentTypeColumnTest.kt` | 1,669 | ❌ noise |
| 8 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V298_DoNotBackupReleaseNotesTest.kt` | 1,586 | ❌ noise |
| 9 | `app/src/test/java/org/thoughtcrime/securesms/database/helpers/migration/V287_FixInvalidArchiveStateTest.kt` | 2,465 | ❌ noise |
| 10 | `app/src/test/java/org/thoughtcrime/securesms/database/DatabaseConsistencyTest.kt` | 8,645 | ❌ noise |
| 11 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V220_PreKeyConstraints.kt` | 822 | ✅ related |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V151_MyStoryMigration.kt` | 1,075 | ✅ related |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V226_AddAttachmentMediaIdIndex.kt` | 148 | ✅ related |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V196_BackCallLinksWithRecipientV2.kt` | 879 | ✅ related |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V162_ThreadUnreadSelfMentionCountFixup.kt` | 340 | ✅ related |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V215_RemoveAttachmentUniqueId.kt` | 886 | ✅ related |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V171_ThreadForeignKeyFix.kt` | 1,417 | ✅ related |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V238_AddGroupSendEndorsementsColumns.kt` | 182 | ✅ related |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V174_ReactionForeignKeyMigration.kt` | 368 | ✅ related |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V228_AddNameCollisionTables.kt` | 341 | ✅ related |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V166_ThreadAndMessageForeignKeys.kt` | 4,055 | ✅ related |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V234_ThumbnailRestoreStateColumn.kt` | 144 | ✅ related |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V200_ResetPniColumn.kt` | 162 | ✅ related |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V153_MyStoryMigration.kt` | 1,075 | ✅ related |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V204_GroupForeignKeyMigration.kt` | 1,026 | ✅ related |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V216_PhoneNumberDiscoverable.kt` | 128 | ✅ related |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V184_CallLinkReplaceIndexMigration.kt` | 453 | ✅ related |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V309_GroupTerminatedColumnMigration.kt` | 143 | ✅ related |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V283_ViewOnceRemoteDataCleanup.kt` | 247 | ✅ related |
| 30 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V227_AddAttachmentArchiveTransferState.kt` | 154 | ✅ related |
| 31 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V214_PhoneNumberSharingColumn.kt` | 149 | ✅ related |
| 32 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V180_RecipientNicknameMigration.kt` | 128 | ✅ related |
| 33 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V282_AddSnippetMessageIdColumnToThreadTable.kt` | 175 | ✅ related |
| 34 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V203_PreKeyStaleTimestamp.kt` | 395 | ✅ related |
| 35 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V209_ClearRecipientPniFromAciColumn.kt` | 149 | ✅ related |
| 36 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V273_FixUnreadOriginalMessages.kt` | 214 | ✅ related |
| 37 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V201_RecipientTableValidations.kt` | 1,290 | ✅ related |
| 38 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V312_RefactorNameCollisionTables.kt` | 513 | ✅ related |
| 39 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V268_FixInAppPaymentsErrorStateConsistency.kt` | 540 | ✅ related |
| 40 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V160_SmsMmsExportedIndexMigration.kt` | 129 | ✅ related |
| 41 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V316_AddVerifiedGroupNameHashMigration.kt` | 110 | ✅ related |
| 42 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V288_CopyStickerDataHashStartToEnd.kt` | 186 | ✅ related |
| 43 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V167_RecreateReactionTriggers.kt` | 293 | ✅ related |
| 44 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/SignalDatabaseMigrations.kt` | 6,582 | ✅ related |
| 45 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V150_UrgentMslFlagMigration.kt` | 148 | ✅ related |
| 46 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V243_MessageFullTextSearchDisableSecureDelete.kt` | 237 | ✅ related |
| 47 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V302_AddDeletedByColumn.kt` | 345 | ✅ related |
| 48 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V280_RemoveAttachmentIv.kt` | 484 | ✅ related |
| 49 | `app/src/main/java/org/thoughtcrime/securesms/database/SignalDatabase.kt` | 5,362 | ❌ noise |
| 50 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V303_CaseInsensitiveUsernames.kt` | 338 | ✅ related |
| 51 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V313_AddCollapsingUpdateColumns.kt` | 286 | ✅ related |
| 52 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V297_AddPinnedMessageColumns.kt` | 205 | ✅ related |
| 53 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V294_RemoveLastResortKeyTupleColumnConstraintMigration.kt` | 235 | ✅ related |
| 54 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V286_FixRemoteKeyEncoding.kt` | 347 | ✅ related |
| 55 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V306_AddRemoteDeletedColumn.kt` | 221 | ✅ related |
| 56 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V172_GroupMembershipMigration.kt` | 511 | ✅ related |
| 57 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V179_CleanupDanglingMessageSendLogMigration.kt` | 162 | ✅ related |
| 58 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V247_ClearUploadTimestamp.kt` | 205 | ✅ related |
| 59 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V157_RecipeintHiddenMigration.kt` | 106 | ✅ related |
| 60 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V287_FixInvalidArchiveState.kt` | 167 | ✅ related |
| 61 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V277_AddNotificationProfileStorageSync.kt` | 539 | ✅ related |
| 62 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V199_AddThreadActiveColumn.kt` | 357 | ✅ related |
| 63 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V314_FixMessageRequestAcceptedToRecipient.kt` | 168 | ✅ related |
| 64 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V266_UniqueThreadPinOrder.kt` | 1,326 | ✅ related |
| 65 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V272_UpdateUnreadCountIndices.kt` | 203 | ✅ related |
| 66 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V154_PniSignaturesMigration.kt` | 262 | ✅ related |
| 67 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V304_CallAndReplyNotificationSettings.kt` | 159 | ✅ related |
| 68 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V210_FixPniPossibleColumns.kt` | 629 | ✅ related |
| 69 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V257_CreateBackupMediaSyncTable.kt` | 179 | ✅ related |
| 70 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V245_DeletionTimestampOnCallLinks.kt` | 156 | ✅ related |
| 71 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V256_FixIncrementalDigestColumns.kt` | 227 | ✅ related |
| 72 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V319_AddAttachmentAndMessageIndexes.kt` | 182 | ✅ related |
| 73 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V188_FixMessageRecipientsAndEditMessageMigration.kt` | 3,565 | ✅ related |
| 74 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V222_DataHashRefactor.kt` | 240 | ✅ related |
| 75 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V191_UniqueMessageMigrationV2.kt` | 2,749 | ✅ related |
| 76 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V161_StorySendMessageIdIndex.kt` | 141 | ✅ related |
| 77 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V263_InAppPaymentsSubscriberTableRebuild.kt` | 539 | ✅ related |
| 78 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V321_AddScheduledMessageIndex.kt` | 131 | ✅ related |
| 79 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V300_AddKeyTransparencyColumn.kt` | 126 | ✅ related |
| 80 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V301_RemoveCallLinkEpoch.kt` | 177 | ✅ related |
| 81 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V223_AddNicknameAndNoteFieldsToRecipientTable.kt` | 222 | ✅ related |
| 82 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V176_AddScheduledDateToQuoteIndex.kt` | 163 | ✅ related |
| 83 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V195_GroupMemberForeignKeyMigration.kt` | 738 | ✅ related |
| 84 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V207_AddChunkSizeColumn.kt` | 138 | ✅ related |
| 85 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V194_KyberPreKeyMigration.kt` | 244 | ✅ related |
| 86 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V237_ResetGroupForceUpdateTimestamps.kt` | 150 | ✅ related |
| 87 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V258_FixGroupRevokedInviteeUpdate.kt` | 959 | ✅ related |
| 88 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V267_FixGroupInvitationDeclinedUpdate.kt` | 712 | ✅ related |
| 89 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V232_CreateInAppPaymentTable.kt` | 319 | ✅ related |
| 90 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V178_ReportingTokenColumnMigration.kt` | 131 | ✅ related |
| 91 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V177_MessageSendLogTableCleanupMigration.kt` | 546 | ✅ related |
| 92 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V189_CreateCallLinkTableColumnsAndRebuildFKReference.kt` | 659 | ✅ related |
| 93 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V240_MessageFullTextSearchSecureDelete.kt` | 184 | ✅ related |
| 94 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V163_RemoteMegaphoneSnoozeSupportMigration.kt` | 374 | ✅ related |
| 95 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V244_AttachmentRemoteIv.kt` | 135 | ✅ related |
| 96 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V219_PniPreKeyStores.kt` | 238 | ✅ related |
| 97 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V225_AddLocalUserJoinedStateAndGroupCallActiveState.kt` | 261 | ✅ related |
| 98 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V291_NullOutRemoteKeyIfEmpty.kt` | 159 | ✅ related |
| 99 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V241_ExpireTimerVersion.kt` | 209 | ✅ related |
| 100 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V217_MessageTableExtrasColumn.kt` | 191 | ✅ related |
| 101 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V270_FixChatFolderColumnsForStorageSync.kt` | 454 | ✅ related |
| 102 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V255_AddCallTableLogIndex.kt` | 155 | ✅ related |
| 103 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V197_DropAvatarColorFromCallLinks.kt` | 155 | ✅ related |
| 104 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V295_AddLastRestoreKeyTypeTableIfMissingMigration.kt` | 233 | ✅ related |
| 105 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V165_MmsMessageBoxPaymentTransactionIndexMigration.kt` | 166 | ✅ related |
| 106 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V269_BackupMediaSnapshotChanges.kt` | 305 | ✅ related |
| 107 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V202_DropMessageTableThreadDateIndex.kt` | 140 | ✅ related |
| 108 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V311_AddAttachmentMediaOverviewSizeIndex.kt` | 174 | ✅ related |
| 109 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V285_AddEpochToCallLinksTable.kt` | 128 | ✅ related |
| 110 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V183_CallLinkTableMigration.kt` | 422 | ✅ related |
| 111 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V235_AttachmentUuidColumn.kt` | 141 | ✅ related |
| 112 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V318_AddMessageNotificationStateIndex.kt` | 306 | ✅ related |
| 113 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V320_AddAttachmentThumbnailFileAndUuidIndexes.kt` | 187 | ✅ related |
| 114 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V260_RemapQuoteAuthors.kt` | 573 | ✅ related |
| 115 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V168_SingleMessageTableMigration.kt` | 1,360 | ✅ related |
| 116 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V230_UnreadCountIndices.kt` | 185 | ✅ related |
| 117 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V190_UniqueMessageMigration.kt` | 129 | ✅ related |
| 118 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V182_CallTableMigration.kt` | 518 | ✅ related |
| 119 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V211_ReceiptColumnRenames.kt` | 226 | ✅ related |
| 120 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V261_RemapCallRingers.kt` | 531 | ✅ related |
| 121 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V233_FixInAppPaymentTableDefaultNotifiedValue.kt` | 341 | ✅ related |
| 122 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V239_MessageFullTextSearchEmojiSupport.kt` | 715 | ✅ related |
| 123 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V290_AddArchiveThumbnailTransferStateColumn.kt` | 157 | ✅ related |
| 124 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V264_FixGroupAddMemberUpdate.kt` | 717 | ✅ related |
| 125 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V231_ArchiveThumbnailColumns.kt` | 193 | ✅ related |
| 126 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V254_AddChatFolderConstraint.kt` | 414 | ✅ related |
| 127 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V193_BackCallLinksWithRecipient.kt` | 132 | ✅ related |
| 128 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V305_AddStoryArchivedColumn.kt` | 231 | ✅ related |
| 129 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V186_ForeignKeyIndicesMigration.kt` | 839 | ✅ related |
| 130 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V169_EmojiSearchIndexRank.kt` | 256 | ✅ related |
| 131 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V213_FixUsernameInE164Column.kt` | 512 | ✅ related |
| 132 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V242_MessageFullTextSearchEmojiSupportV2.kt` | 683 | ✅ related |
| 133 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V164_ThreadDatabaseReadIndexMigration.kt` | 107 | ✅ related |
| 134 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V236_FixInAppSubscriberCurrencyIfAble.kt` | 669 | ✅ related |
| 135 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V292_AddPollTables.kt` | 605 | ✅ related |
| 136 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V315_CleanupE164SenderKeyShared.kt` | 105 | ✅ related |
| 137 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V175_FixFullTextSearchLink.kt` | 524 | ✅ related |
| 138 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V284_SetPlaceholderGroupFlag.kt` | 468 | ✅ related |
| 139 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V289_AddQuoteTargetContentTypeColumn.kt` | 202 | ✅ related |
| 140 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V279_AddNotificationProfileForeignKey.kt` | 482 | ✅ related |
| 141 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V218_RecipientPniSignatureVerified.kt` | 175 | ✅ related |
| 142 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V170_CallTableMigration.kt` | 224 | ✅ related |
| 143 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V296_RemovePollVoteConstraint.kt` | 446 | ✅ related |
| 144 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V252_AttachmentOffloadRestoredAtColumn.kt` | 244 | ✅ related |
| 145 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V271_AddNotificationProfileIdColumn.kt` | 247 | ✅ related |
| 146 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V181_ThreadTableForeignKeyCleanup.kt` | 522 | ✅ related |
| 147 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V192_CallLinkTableNullableRootKeys.kt` | 349 | ✅ related |
| 148 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V156_RecipientUnregisteredTimestampMigration.kt` | 320 | ✅ related |
| 149 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V274_BackupMediaSnapshotLastSeenOnRemote.kt` | 164 | ✅ related |
| 150 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V299_AddAttachmentMetadataTable.kt` | 238 | ✅ related |
| 151 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V281_RemoveArchiveTransferFile.kt` | 179 | ✅ related |
| 152 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V221_AddReadColumnToCallEventsTable.kt` | 338 | ✅ related |
| 153 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V275_EnsureDefaultAllChatsFolder.kt` | 262 | ✅ related |
| 154 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V173_ScheduledMessagesMigration.kt` | 218 | ✅ related |
| 155 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V187_MoreForeignKeyIndexesMigration.kt` | 306 | ✅ related |
| 156 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V251_ArchiveTransferStateIndex.kt` | 188 | ✅ related |
| 157 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V310_AddStarredColumn.kt` | 148 | ✅ related |
| 158 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V229_MarkMissedCallEventsNotified.kt` | 183 | ✅ related |
| 159 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V250_ClearUploadTimestampV2.kt` | 172 | ✅ related |
| 160 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V149_LegacyMigrations.kt` | 27,238 | ✅ related |
| 161 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V265_FixFtsTriggers.kt` | 1,029 | ✅ related |
| 162 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V317_AddMessageThreadDateReceivedUnreadIndex.kt` | 212 | ✅ related |
| 163 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V152_StoryGroupTypesMigration.kt` | 142 | ✅ related |
| 164 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V278_BackupSnapshotTableVersions.kt` | 307 | ✅ related |
| 165 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V158_GroupsLastForceUpdateTimestampMigration.kt` | 136 | ✅ related |
| 166 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V205_DropPushTable.kt` | 129 | ✅ related |
| 167 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V253_CreateChatFolderTables.kt` | 469 | ✅ related |
| 168 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V308_AddBackRemoteDeletedColumn.kt` | 225 | ✅ related |
| 169 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V212_RemoveDistributionListUniqueConstraint.kt` | 894 | ✅ related |
| 170 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V259_AdjustNotificationProfileMidnightEndTimes.kt` | 175 | ✅ related |
| 171 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V246_DropThumbnailCdnFromAttachments.kt` | 165 | ✅ related |
| 172 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V198_AddMacDigestColumn.kt` | 134 | ✅ related |
| 173 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V298_DoNotBackupReleaseNotes.kt` | 440 | ✅ related |
| 174 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V224_AddAttachmentArchiveColumns.kt` | 213 | ✅ related |
| 175 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V206_AddConversationCountIndex.kt` | 171 | ✅ related |
| 176 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V159_ThreadUnreadSelfMentionCount.kt` | 111 | ✅ related |
| 177 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V155_SmsExporterMigration.kt` | 181 | ✅ related |
| 178 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V276_AttachmentCdnDefaultValueMigration.kt` | 1,061 | ✅ related |
| 179 | `app/src/main/java/org/thoughtcrime/securesms/database/helpers/migration/V185_MessageRecipientsAndEditMessageMigration.kt` | 3,015 | ✅ related |
| 180 | `app/src/androidTest/java/org/thoughtcrime/securesms/migrations/GooglePlayBillingPurchaseTokenMigrationJobTest.kt` | 1,474 | ✅ related |
| 181 | `app/src/androidTest/java/org/thoughtcrime/securesms/migrations/SubscriberIdMigrationJobTest.kt` | 580 | ✅ related |
| 182 | `app/src/test/java/org/thoughtcrime/securesms/jobs/FastJobStorageTest.kt` | 17,778 | ❌ noise |
| 183 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerLaunchMigrationJob.java` | 600 | ✅ related |
| 184 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PassingMigrationJob.java` | 280 | ✅ related |
| 185 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PinReminderMigrationJob.java` | 299 | ✅ related |
| 186 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ResetKeyTransparencyMigrationJob.kt` | 314 | ✅ related |
| 187 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PnpLaunchMigrationJob.kt` | 300 | ✅ related |
| 188 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageCapabilityMigrationJob.java` | 712 | ✅ related |
| 189 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UpdateSmsJobsMigrationJob.kt` | 801 | ✅ related |
| 190 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ApplicationMigrations.java` | 9,641 | ✅ related |
| 191 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StoryViewedReceiptsStateMigrationJob.kt` | 371 | ✅ related |
| 192 | `app/src/main/java/org/thoughtcrime/securesms/migrations/IdentityTableCleanupMigrationJob.kt` | 584 | ✅ related |
| 193 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackupNotificationMigrationJob.java` | 530 | ✅ related |
| 194 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AttachmentHashBackfillMigrationJob.kt` | 321 | ✅ related |
| 195 | `app/src/main/java/org/thoughtcrime/securesms/migrations/DatabaseMigrationJob.java` | 322 | ✅ related |
| 196 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BadE164MigrationJob.kt` | 1,656 | ✅ related |
| 197 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageServiceMigrationJob.java` | 604 | ✅ related |
| 198 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ApplyUnknownFieldsToSelfMigrationJob.java` | 765 | ✅ related |
| 199 | `app/src/main/java/org/thoughtcrime/securesms/migrations/WallpaperCleanupMigrationJob.kt` | 392 | ✅ related |
| 200 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SyncCallLinksMigrationJob.kt` | 432 | ✅ related |
| 201 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PreKeysSyncMigrationJob.kt` | 260 | ✅ related |
| 202 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ProfileMigrationJob.java` | 352 | ✅ related |
| 203 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackfillNotifiedStateMigrationJob.kt` | 248 | ✅ related |
| 204 | `app/src/main/java/org/thoughtcrime/securesms/migrations/EmojiDownloadMigrationJob.java` | 362 | ✅ related |
| 205 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RecheckPaymentsMigrationJob.kt` | 398 | ✅ related |
| 206 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AvatarMigrationJob.java` | 731 | ✅ related |
| 207 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SyncChatFoldersMigrationJob.kt` | 429 | ✅ related |
| 208 | `app/src/main/java/org/thoughtcrime/securesms/migrations/LegacyMigrationJob.java` | 2,806 | ✅ related |
| 209 | `app/src/main/java/org/thoughtcrime/securesms/migrations/DuplicateE164MigrationJob.kt` | 1,960 | ✅ related |
| 210 | `app/src/main/java/org/thoughtcrime/securesms/migrations/OptimizeMessageSearchIndexMigrationJob.kt` | 269 | ✅ related |
| 211 | `app/src/main/java/org/thoughtcrime/securesms/migrations/DirectoryRefreshMigrationJob.java` | 426 | ✅ related |
| 212 | `app/src/main/java/org/thoughtcrime/securesms/migrations/GooglePlayBillingPurchaseTokenMigrationJob.kt` | 838 | ✅ related |
| 213 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerAdditionMigrationJob.java` | 699 | ✅ related |
| 214 | `app/src/main/java/org/thoughtcrime/securesms/migrations/QuoteThumbnailBackfillMigrationJob.kt` | 622 | ✅ related |
| 215 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackfillDigestsForDuplicatesMigrationJob.kt` | 373 | ✅ related |
| 216 | `app/src/main/java/org/thoughtcrime/securesms/migrations/CachedAttachmentsMigrationJob.java` | 419 | ✅ related |
| 217 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ClearGlideCacheMigrationJob.kt` | 236 | ✅ related |
| 218 | `app/src/main/java/org/thoughtcrime/securesms/migrations/E164FormattingMigrationJob.kt` | 1,786 | ✅ related |
| 219 | `app/src/main/java/org/thoughtcrime/securesms/migrations/EmojiSearchIndexCheckMigrationJob.java` | 417 | ✅ related |
| 220 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SyncDistributionListsMigrationJob.java` | 717 | ✅ related |
| 221 | `app/src/main/java/org/thoughtcrime/securesms/AppInitialization.java` | 982 | ❌ noise |
| 222 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerPackAddition2MigrationJob.kt` | 449 | ✅ related |
| 223 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BlobStorageLocationMigrationJob.java` | 523 | ✅ related |
| 224 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AepMigrationJob.kt` | 394 | ✅ related |
| 225 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AvatarIdRemovalMigrationJob.java` | 379 | ✅ related |
| 226 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AccountRecordMigrationJob.java` | 472 | ✅ related |
| 227 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PinOptOutMigration.java` | 567 | ✅ related |
| 228 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AccountConsistencyMigrationJob.kt` | 378 | ✅ related |
| 229 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UserNotificationMigrationJob.java` | 1,387 | ✅ related |
| 230 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackupJitterMigrationJob.kt` | 370 | ✅ related |
| 231 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AttachmentCleanupMigrationJob.java` | 365 | ✅ related |
| 232 | `app/src/main/java/org/thoughtcrime/securesms/migrations/EmojiSearchEnglishLabelsMigrationJob.kt` | 346 | ✅ related |
| 233 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ResetArchiveTierMigrationJob.kt` | 357 | ✅ related |
| 234 | `app/src/main/java/org/thoughtcrime/securesms/migrations/Svr2MirrorMigrationJob.kt` | 255 | ✅ related |
| 235 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ArchiveBackupIdReservationMigrationJob.kt` | 307 | ✅ related |
| 236 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AttributesMigrationJob.java` | 416 | ✅ related |
| 237 | `app/src/main/java/org/thoughtcrime/securesms/migrations/DeleteDeprecatedLogsMigrationJob.java` | 466 | ✅ related |
| 238 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ContactLinkRebuildMigrationJob.kt` | 681 | ✅ related |
| 239 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RecipientSearchMigrationJob.java` | 382 | ✅ related |
| 240 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ProfileSharingUpdateMigrationJob.java` | 376 | ✅ related |
| 241 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerMyDailyLifeMigrationJob.java` | 368 | ✅ related |
| 242 | `app/src/main/java/org/thoughtcrime/securesms/migrations/UuidMigrationJob.java` | 713 | ✅ related |
| 243 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SubscriberIdMigrationJob.kt` | 487 | ✅ related |
| 244 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PniAccountInitializationMigrationJob.java` | 994 | ✅ related |
| 245 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RebuildMessageSearchIndexMigrationJob.kt` | 380 | ✅ related |
| 246 | `app/src/main/java/org/thoughtcrime/securesms/migrations/ReleaseChannelRecipientFixMigrationJob.kt` | 307 | ✅ related |
| 247 | `app/src/main/java/org/thoughtcrime/securesms/migrations/TrimByLengthSettingsMigrationJob.java` | 547 | ✅ related |
| 248 | `app/src/main/java/org/thoughtcrime/securesms/migrations/FixChangeNumberErrorMigrationJob.kt` | 691 | ✅ related |
| 249 | `app/src/main/java/org/thoughtcrime/securesms/migrations/BackfillCollapsedEventsMigrationJob.kt` | 277 | ✅ related |
| 250 | `app/src/main/java/org/thoughtcrime/securesms/migrations/AvatarColorStorageServiceMigrationJob.kt` | 364 | ✅ related |
| 251 | `app/src/main/java/org/thoughtcrime/securesms/migrations/PniMigrationJob.java` | 515 | ✅ related |
| 252 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageServiceSystemNameMigrationJob.java` | 381 | ✅ related |
| 253 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StorageFixLocalUnknownMigrationJob.kt` | 556 | ✅ related |
| 254 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SelfRegisteredStateMigrationJob.kt` | 433 | ✅ related |
| 255 | `app/src/main/java/org/thoughtcrime/securesms/migrations/WallpaperStorageMigrationJob.kt` | 951 | ✅ related |
| 256 | `app/src/main/java/org/thoughtcrime/securesms/migrations/StickerDayByDayMigrationJob.java` | 360 | ✅ related |
| 257 | `app/src/main/java/org/thoughtcrime/securesms/migrations/CopyUsernameToSignalStoreMigrationJob.kt` | 429 | ✅ related |
| 258 | `app/src/main/java/org/thoughtcrime/securesms/migrations/SyncKeysMigrationJob.kt` | 279 | ✅ related |
| 259 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ❌ noise |
| 260 | `app/src/main/java/org/thoughtcrime/securesms/jobs/StorageSyncJob.kt` | 8,029 | ❌ noise |
| 261 | `app/src/main/java/org/thoughtcrime/securesms/jobs/AccountConsistencyWorkerJob.kt` | 940 | ❌ noise |
| 262 | `app/src/main/java/org/thoughtcrime/securesms/jobs/E164FormattingJob.kt` | 334 | ❌ noise |

## Analysis

- **Most token-efficient:** RAG+AST (1,300 tokens)
- **Highest precision:** RAG+AST (100.0% golden)
- **Highest signal%:** RAG+AST (100.0% golden+related)
- **Most noise:** Vanilla (rg) (13 irrelevant files read)
