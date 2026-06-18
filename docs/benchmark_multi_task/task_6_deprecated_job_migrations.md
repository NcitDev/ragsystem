# Task 6: Deprecated Job Migrations (Text)

**Query:** Find deprecated job migration code that needs cleanup
**Symbols:** DeprecatedJobMigration, PushDecryptMessageJobEnvelopeMigration
**Search patterns:** @Deprecated, DeprecatedJobMigration, PushDecryptMessageJobEnvelopeMigration
**Golden set (3 files):**
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java`
- `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt`

## Effort Comparison

| Agent | Turns | Tokens | Files Read | Coverage | Latency |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 5 | 2,188 | 3 | 100.0% | 477ms |
| AST-Index | 9 | 12,231 | 4 | 100.0% | 106ms |
| Graphify | 4 | 1,293 | 3 | 100.0% | 2545ms |
| Vanilla (rg) | 33 | 153,298 | 30 | 100.0% | 193ms |

## Information Relevance

How much of what each agent read was actually useful?

| Agent | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 3 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 3 | 0 | 1 | 75.0% | 75.0% |
| Graphify | 3 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 3 | 0 | 27 | 10.0% | 10.0% |

- **Golden** = file is in the required golden set
- **Related** = same package or name matches a task symbol
- **Noise** = unrelated file that was read unnecessarily
- **Precision** = golden / total files read
- **Signal%** = (golden + related) / total files read

### RAG+AST — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 158 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt` | 54 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 1,976 | ⭐ golden |

### AST-Index — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt` | 212 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 398 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 988 | ⭐ golden |
| 4 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ❌ noise |

### Graphify — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt` | 106 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 199 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 988 | ⭐ golden |

### Vanilla (rg) — File Detail

| # | File | Tokens | Relevance |
|---:|------|---:|---|
| 1 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/DeprecatedJobMigration.kt` | 212 | ⭐ golden |
| 2 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java` | 398 | ⭐ golden |
| 3 | `app/src/main/java/org/thoughtcrime/securesms/jobmanager/migrations/PushProcessMessageJobMigration.kt` | 988 | ⭐ golden |
| 4 | `lib/glide/src/main/java/org/signal/glide/load/resource/bitmap/Downsampler.java` | 9,899 | ❌ noise |
| 5 | `lib/photoview/src/main/java/com/github/chrisbanes/photoview/PhotoViewAttacher.java` | 7,537 | ❌ noise |
| 6 | `app/src/main/java/org/thoughtcrime/securesms/conversation/colors/Colorizer.kt` | 1,343 | ❌ noise |
| 7 | `feature/registration/src/main/java/org/signal/registration/screens/captcha/CaptchaScreen.kt` | 1,245 | ❌ noise |
| 8 | `lib/libsignal-service/src/main/java/org/whispersystems/signalservice/api/payments/Money.java` | 1,733 | ❌ noise |
| 9 | `app/src/main/java/org/thoughtcrime/securesms/registration/ui/captcha/CaptchaFragment.kt` | 468 | ❌ noise |
| 10 | `app/src/main/java/org/thoughtcrime/securesms/mediasend/v2/gallery/MediaGalleryFragment.kt` | 3,716 | ❌ noise |
| 11 | `app/src/main/java/org/conscrypt/ConscryptSignal.java` | 7,363 | ❌ noise |
| 12 | `app/src/main/java/org/thoughtcrime/securesms/migrations/RebuildMessageSearchIndexMigrationJob.kt` | 380 | ❌ noise |
| 13 | `app/src/main/java/org/thoughtcrime/securesms/mediapreview/RecycledBitmapGuardDrawable.kt` | 434 | ❌ noise |
| 14 | `app/src/main/java/org/thoughtcrime/securesms/util/DynamicLanguage.java` | 417 | ❌ noise |
| 15 | `app/src/main/java/org/thoughtcrime/securesms/util/SingleLiveEvent.java` | 595 | ❌ noise |
| 16 | `app/src/main/java/org/thoughtcrime/securesms/util/views/SimpleProgressDialog.java` | 1,231 | ❌ noise |
| 17 | `app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java` | 4,232 | ❌ noise |
| 18 | `app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java` | 9,887 | ❌ noise |
| 19 | `app/src/main/java/org/thoughtcrime/securesms/recipients/RecipientRepository.kt` | 1,239 | ❌ noise |
| 20 | `app/src/main/java/org/thoughtcrime/securesms/components/spoiler/SpoilerDrawable.kt` | 294 | ❌ noise |
| 21 | `app/src/main/java/org/thoughtcrime/securesms/database/MessageTable.kt` | 65,644 | ❌ noise |
| 22 | `app/src/main/java/org/thoughtcrime/securesms/components/ContactFilterView.java` | 1,791 | ❌ noise |
| 23 | `app/src/main/java/org/thoughtcrime/securesms/components/emoji/SystemEmojiDrawable.kt` | 540 | ❌ noise |
| 24 | `app/src/main/java/org/thoughtcrime/securesms/keyvalue/AccountValues.kt` | 7,109 | ❌ noise |
| 25 | `app/src/main/java/org/thoughtcrime/securesms/keyvalue/InAppPaymentValues.kt` | 5,423 | ❌ noise |
| 26 | `app/src/main/java/org/thoughtcrime/securesms/components/webrtc/ToggleButtonOutputState.kt` | 784 | ❌ noise |
| 27 | `app/src/main/java/org/thoughtcrime/securesms/service/webrtc/ActiveCallManager.kt` | 4,747 | ❌ noise |
| 28 | `app/src/main/java/org/thoughtcrime/securesms/avatar/picker/AvatarPickerFragment.kt` | 2,557 | ❌ noise |
| 29 | `app/src/main/java/org/thoughtcrime/securesms/jobs/CleanPreKeysJob.java` | 459 | ❌ noise |
| 30 | `app/src/main/java/org/thoughtcrime/securesms/jobs/JobManagerFactories.java` | 10,633 | ❌ noise |

## Analysis

- **Most token-efficient:** Graphify (1,293 tokens)
- **Highest precision:** RAG+AST (100.0% golden)
- **Highest signal%:** RAG+AST (100.0% golden+related)
- **Most noise:** Vanilla (rg) (27 irrelevant files read)
