# Signal-Android Benchmark: Qualitative Results Comparison

## Task 1: Exact Symbol
**Prompt:** Find the definition of MessageFetchJob.

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java:23-115
```java
/**
 * Fetches messages from the service, posting a foreground service if possible if the app is in the background.
 */
public final class MessageFetchJob extends BaseJob {

  public static final String KEY = "PushNotificationReceiveJob";

  private static final String TAG = Log.tag(MessageFetchJob.class);

  public MessageFetchJob() {
    this(new Job.Parameters.Builder()
             .addConstraint(NetworkConstraint.KEY)
             .setQueue("__notification_received")
             .setMaxAtt...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java:23-115
```java
/**
 * Fetches messages from the service, posting a foreground service if possible if the app is in the background.
 */
public final class MessageFetchJob extends BaseJob {

  public static final String KEY = "PushNotificationReceiveJob";

  private static final String TAG = Log.tag(MessageFetchJob.class);

  public MessageFetchJob() {
    this(new Job.Parameters.Builder()
             .addConstraint(NetworkConstraint.KEY)
             .setQueue("__notification_received")
             .setMaxAtt...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java:166-171
```java
  public static final class Factory implements Job.Factory<MessageFetchJob> {
    @Override
    public @NonNull MessageFetchJob create(@NonNull Parameters parameters, @Nullable byte[] serializedData) {
      return new MessageFetchJob(parameters);
    }
  }...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/gcm/FcmFetchManager.kt:163-180
```java
  @JvmStatic
  fun retrieveMessages(context: Context): Boolean {
    val success = WebSocketDrainer.blockUntilDrainedAndProcessed(WEBSOCKET_DRAIN_TIMEOUT, KEEP_ALIVE_TOKEN)

    if (success) {
      Log.i(TAG, "Successfully retrieved messages.")
    } else {
      if (Build.VERSION.SDK_INT >= 26) {
        Log.w(TAG, "[API ${Build.VERSION.SDK_INT}] Failed to retrieve messages. Scheduling on the system JobScheduler (API " + Build.VERSION.SDK_INT + ").")
        FcmJobService.schedule(context)
   ...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['MessageFetchJob'] | 696 nodes found

NODE MessageFetchJob.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java loc=L1 community=]
NODE RoutineMessageFetchReceiver.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/messageprocessingalarm/RoutineMessageFetchReceiver.java loc=L1 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java loc=L50 community=]
NODE BaseJob.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/BaseJob.java loc=L1 community=]
NODE MigrationCompleteJob.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/migrations/MigrationCompleteJob.java loc=L1 community=]
NODE Nullable [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java loc=L45 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L187 community=]
NODE BootReceiver.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/BootReceiver.java loc=L1 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L40 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/megaphone/Megaphones.java loc=L89 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/providers/BlobProvider.java loc=L102 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/sms/MessageSender.java loc=L100 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/profiles/AvatarHelper.java loc=L41 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/mediasend/MediaRepository.java loc=L61 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/crypto/MasterSecretUtil.java loc=L69 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/model/MessageRecord.java loc=L193 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/mms/MediaConstraints.java loc=L36 community=]
... (truncated — 679 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 2: Semantic Intent
**Prompt:** Find where Signal processes incoming push notifications.

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/jobs/MessageFetchJob.java:23-115
```java
/**
 * Fetches messages from the service, posting a foreground service if possible if the app is in the background.
 */
public final class MessageFetchJob extends BaseJob {

  public static final String KEY = "PushNotificationReceiveJob";

  private static final String TAG = Log.tag(MessageFetchJob.class);

  public MessageFetchJob() {
    this(new Job.Parameters.Builder()
             .addConstraint(NetworkConstraint.KEY)
             .setQueue("__notification_received")
             .setMaxAtt...
```

### [AST DEF] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:40-49
```java
  @Test
  fun pushChallengeBlocking_waits_for_specified_period() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 250L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isGreaterThanOrEqualTo(250L)
  }...
```

### [AST DEF] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:31-38
```java
  @Test
  fun pushChallengeBlocking_returns_absent_if_times_out() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val challenge = PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 50L)

    assertThat(challenge).isAbsent()
  }...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:51-70
```java
  @Test
  fun pushChallengeBlocking_completes_fast_if_posted_to_event_bus() {
    val signal = mockk<SignalServiceAccountManager> {
      every {
        requestRegistrationPushChallenge("session ID", "token")
      } answers {
        AsyncTask.execute { PushChallengeRequest.postChallengeResponse("CHALLENGE") }
      }
    }

    val startTime = System.currentTimeMillis()
    val challenge = PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 500L)
    val ...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:40-49
```java
  @Test
  fun pushChallengeBlocking_waits_for_specified_period() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 250L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isGreaterThanOrEqualTo(250L)
  }...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:72-81
```java
  @Test
  fun pushChallengeBlocking_returns_fast_if_no_fcm_token_supplied() {
    val signal = mockk<SignalServiceAccountManager>()

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.empty(), 500L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isLessThan(500L)
  }...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['Incoming', 'Push', 'Push'] | 42 nodes found

NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L40 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L40 community=]
NODE RecipientId [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L40 community=]
NODE WorkerThread [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L40 community=]
NODE Recipients [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/RemappedRecordTables.kt loc=L35 community=]
NODE Groups [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/contacts/paged/ContactSearchConfiguration.kt loc=L98 community=]
NODE Messages [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/contacts/paged/ContactSearchConfiguration.kt loc=L172 community=]
NODE GroupTable [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/GroupTable.kt loc=L85 community=]
NODE Collection [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L131 community=]
NODE .requireV2() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupId.kt loc=L242 community=]
NODE GroupManager [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManager.java loc=L36 community=]
NODE .edit() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java loc=L194 community=]
NODE .requireV2GroupProperties() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/model/GroupRecord.kt loc=L179 community=]
NODE Boolean [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/GroupTable.kt loc=L277 community=]
NODE RecipientId [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/GroupTable.kt loc=L217 community=]
NODE .deleteMessageRequest() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/messagerequests/MessageRequestRepository.java loc=L239 community=]
NODE .requireGroup() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/GroupTable.kt loc=L269 community=]
... (truncated — 25 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 3: Deep Architecture
**Prompt:** How does Signal handle database migrations?

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/migrations/DatabaseMigrationJob.java:9-51
```java
/**
 * Triggers a database access, forcing the database to upgrade if it hasn't already. Should be used
 * when you expect a database migration to take a particularly long time.
 */
public class DatabaseMigrationJob extends MigrationJob {

  public static final String KEY = "DatabaseMigrationJob";

  DatabaseMigrationJob() {
    this(new Parameters.Builder().build());
  }

  private DatabaseMigrationJob(@NonNull Parameters parameters) {
    super(parameters);
  }

  @Override
  public boolean is...
```

### [AST DEF] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:40-49
```java
  @Test
  fun pushChallengeBlocking_waits_for_specified_period() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 250L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isGreaterThanOrEqualTo(250L)
  }...
```

### [AST DEF] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:31-38
```java
  @Test
  fun pushChallengeBlocking_returns_absent_if_times_out() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val challenge = PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 50L)

    assertThat(challenge).isAbsent()
  }...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:51-70
```java
  @Test
  fun pushChallengeBlocking_completes_fast_if_posted_to_event_bus() {
    val signal = mockk<SignalServiceAccountManager> {
      every {
        requestRegistrationPushChallenge("session ID", "token")
      } answers {
        AsyncTask.execute { PushChallengeRequest.postChallengeResponse("CHALLENGE") }
      }
    }

    val startTime = System.currentTimeMillis()
    val challenge = PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 500L)
    val ...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:40-49
```java
  @Test
  fun pushChallengeBlocking_waits_for_specified_period() {
    val signal = mockk<SignalServiceAccountManager>(relaxUnitFun = true)

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.of("token"), 250L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isGreaterThanOrEqualTo(250L)
  }...
```

### [RAG CHUNK] app/src/test/java/org/thoughtcrime/securesms/registration/fcm/PushChallengeRequestTest.kt:72-81
```java
  @Test
  fun pushChallengeBlocking_returns_fast_if_no_fcm_token_supplied() {
    val signal = mockk<SignalServiceAccountManager>()

    val startTime = System.currentTimeMillis()
    PushChallengeRequest.getPushChallengeBlocking(signal, "session ID", Optional.empty(), 500L)
    val duration = System.currentTimeMillis() - startTime

    assertThat(duration).isLessThan(500L)
  }...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['DatabaseMigrationJob', 'DatabaseMigrationJob.java', 'DatabaseCorruptedError_BothChecksFail'] | 4995 nodes found

NODE ConversationItem.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationItem.java loc=L1 community=]
NODE ConversationListFragment.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversationlist/ConversationListFragment.java loc=L1 community=]
NODE ContactSelectionListFragment.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/ContactSelectionListFragment.java loc=L1 community=]
NODE InputPanel.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/InputPanel.java loc=L1 community=]
NODE SharedContactDetailsActivity.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/contactshare/SharedContactDetailsActivity.java loc=L1 community=]
NODE ConversationListItem.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversationlist/ConversationListItem.java loc=L1 community=]
NODE AddGroupDetailsFragment.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/ui/creategroup/details/AddGroupDetailsFragment.java loc=L1 community=]
NODE SignalCallManager.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java loc=L1 community=]
NODE ImageEditorFragment.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/scribbles/ImageEditorFragment.java loc=L1 community=]
NODE ShowAdminsBottomSheetDialog.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ShowAdminsBottomSheetDialog.java loc=L1 community=]
NODE MediaGalleryAllAdapter.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/mediaoverview/MediaGalleryAllAdapter.java loc=L1 community=]
NODE GroupManagerV2.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java loc=L1 community=]
NODE ConversationAdapter.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationAdapter.java loc=L1 community=]
NODE ConversationUpdateItem.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationUpdateItem.java loc=L1 community=]
NODE AttachmentManager.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/mms/AttachmentManager.java loc=L1 community=]
... (truncated — 4980 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 4: Dependency Injection
**Prompt:** How is OkHttpClient provided?

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/video/exo/SimpleExoPlayerPool.kt:22-78
```java
/**
 * ExoPlayerPool concrete instance which helps to manage a pool of ExoPlayer objects
 */
@OptIn(markerClass = [UnstableApi::class])
class SimpleExoPlayerPool(context: Context) : ExoPlayerPool<ExoPlayer>(MAXIMUM_RESERVED_PLAYERS) {
  private val context: Context = context.applicationContext
  private val okHttpClient = AppDependencies.okHttpClient.newBuilder().proxySelector(ContentProxySelector()).build()
  private val dataSourceFactory: DataSource.Factory = SignalDataSource.Factory(AppDepend...
```

### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/video/exo/SignalDataSource.java:96-112
```java
      return "http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme);
    } else {
      return false;
    }
  }

  public static final class Factory implements DataSource.Factory {
    private final Context                  context;
    private final OkHttpClient             okHttpClient;
    private final TransferListener         listener;

    public Factory(@NonNull Context context,
                   @Nullable OkHttpClient okHttpClient,
                   @Nullable TransferListe...
```

### [AST DEF] demo/registration/src/main/java/org/signal/registration/sample/dependencies/DemoNetworkController.kt:90-90
```java
class DemoNetworkController(...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/video/exo/SimpleExoPlayerPool.kt:22-78
```java
/**
 * ExoPlayerPool concrete instance which helps to manage a pool of ExoPlayer objects
 */
@OptIn(markerClass = [UnstableApi::class])
class SimpleExoPlayerPool(context: Context) : ExoPlayerPool<ExoPlayer>(MAXIMUM_RESERVED_PLAYERS) {
  private val context: Context = context.applicationContext
  private val okHttpClient = AppDependencies.okHttpClient.newBuilder().proxySelector(ContentProxySelector()).build()
  private val dataSourceFactory: DataSource.Factory = SignalDataSource.Factory(AppDepend...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/video/exo/ChunkedDataSource.java:27-110
```java
/**
 * DataSource which utilizes ChunkedDataFetcher to download video content via Signal content proxy.
 */
@OptIn(markerClass = UnstableApi.class)
class ChunkedDataSource implements DataSource {

  private final OkHttpClient     okHttpClient;
  private final TransferListener transferListener;

  private DataSpec               dataSpec;
  private GiphyMp4Cache.ReadData cacheEntry;

  private volatile Exception exception;

  ChunkedDataSource(@NonNull OkHttpClient okHttpClient, @Nullable Transfer...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/s3/S3.kt:32-114
```java
/**
 * Generic methods for communicating with S3
 */
object S3 {
  private val TAG = Log.tag(S3::class.java)

  private val okHttpClient by lazy { AppDependencies.signalOkHttpClient }

  const val DYNAMIC_PATH = "/dynamic"
  const val STATIC_PATH = "/static"

  /**
   * Fetches the content at the given endpoint and attempts to return it as a string.
   *
   * @param endpoint The endpoint at which to get the long
   * @return the string value of the body
   * @throws IOException if the call fails...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['OkHttpClient', 'OkHttpClient', 'OkHttpClient'] | 1892 nodes found

NODE LinkPreviewRepository.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/linkpreview/LinkPreviewRepository.java loc=L1 community=]
NODE SubmitDebugLogRepository.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/logsubmit/SubmitDebugLogRepository.java loc=L1 community=]
NODE SignalDataSource.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/video/exo/SignalDataSource.java loc=L1 community=]
NODE ChunkedDataSource.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/video/exo/ChunkedDataSource.java loc=L1 community=]
NODE GiphyMp4PagedDataSource.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/giph/mp4/GiphyMp4PagedDataSource.java loc=L1 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/WebRtcActionProcessor.java loc=L97 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java loc=L154 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/state/WebRtcServiceStateBuilder.java loc=L44 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java loc=L144 community=]
NODE ChunkedDataFetcher.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/net/ChunkedDataFetcher.java loc=L1 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/messages/GroupSendUtil.java loc=L564 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java loc=L54 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationIntents.java loc=L67 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java loc=L295 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/OutgoingCallActionProcessor.java loc=L58 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/IncomingCallActionProcessor.java loc=L60 community=]
... (truncated — 1876 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 5: Blast Radius
**Prompt:** What depends on SignalServiceAccountManager?

### [Tool: RAG + AST]
### [AST DEF] lib/libsignal-service/src/main/java/org/whispersystems/signalservice/api/SignalServiceAccountManager.java:30-125
```java
/**
 * The main interface for creating, registering, and
 * managing a Signal Service account.
 *
 * @author Moxie Marlinspike
 */
public class SignalServiceAccountManager {

  private static final String TAG = SignalServiceAccountManager.class.getSimpleName();

  private final PushServiceSocket                      pushServiceSocket;
  private final GroupsV2Operations                     groupsV2Operations;
  private final SignalServiceConfiguration             configuration;
  private final Si...
```

### [AST DEF] core/util/src/main/java/org/signal/core/util/ThrottledDebouncer.java:16-32
```java
 * However, like a debouncer, instead of completely discarding runnables that are published in the
 * throttling period, the most recent one will be saved and run at the end of the throttling period.
 *
 * Useful for publishing a set of identical or near-identical tasks that you want to be responsive
 * and guaranteed, but limited in execution frequency.
 */
public class ThrottledDebouncer {

  private static final int WHAT = 24601;

  private final OverflowHandler handler;
  private final long ...
```

### [AST DEF] core/util/src/main/java/org/signal/core/util/Throttler.java:12-28
```java
 *
 * This is different from {@link Debouncer} in that it will run the first runnable immediately
 * instead of waiting for input to die down.
 *
 * See http://rxmarbles.com/#throttle
 */
public class Throttler {

  private static final int WHAT = 8675309;

  private final Handler handler;
  private final long    threshold;

  /**
   * @param threshold Only one runnable will be executed via {@link #publish(Runnable)} every
   *                  {@code threshold} milliseconds.
   */...
```

### [RAG CHUNK] core/util/src/main/java/org/signal/core/util/ThrottledDebouncer.java:16-32
```java
 * However, like a debouncer, instead of completely discarding runnables that are published in the
 * throttling period, the most recent one will be saved and run at the end of the throttling period.
 *
 * Useful for publishing a set of identical or near-identical tasks that you want to be responsive
 * and guaranteed, but limited in execution frequency.
 */
public class ThrottledDebouncer {

  private static final int WHAT = 24601;

  private final OverflowHandler handler;
  private final long ...
```

### [RAG CHUNK] core/util/src/main/java/org/signal/core/util/Throttler.java:12-28
```java
 *
 * This is different from {@link Debouncer} in that it will run the first runnable immediately
 * instead of waiting for input to die down.
 *
 * See http://rxmarbles.com/#throttle
 */
public class Throttler {

  private static final int WHAT = 8675309;

  private final Handler handler;
  private final long    threshold;

  /**
   * @param threshold Only one runnable will be executed via {@link #publish(Runnable)} every
   *                  {@code threshold} milliseconds.
   */...
```

### [RAG CHUNK] lib/libsignal-service/src/main/java/org/whispersystems/signalservice/api/SignalServiceAccountManager.java:30-125
```java
/**
 * The main interface for creating, registering, and
 * managing a Signal Service account.
 *
 * @author Moxie Marlinspike
 */
public class SignalServiceAccountManager {

  private static final String TAG = SignalServiceAccountManager.class.getSimpleName();

  private final PushServiceSocket                      pushServiceSocket;
  private final GroupsV2Operations                     groupsV2Operations;
  private final SignalServiceConfiguration             configuration;
  private final Si...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['SignalServiceAccountManager', 'SignalServiceAccountManager', 'SignalServiceAccountManager'] | 1315 nodes found

NODE GroupCandidateHelper.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/v2/GroupCandidateHelper.java loc=L1 community=]
NODE AccountManagerFactory.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/push/AccountManagerFactory.java loc=L1 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/WebRtcActionProcessor.java loc=L97 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/state/WebRtcServiceStateBuilder.java loc=L44 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java loc=L154 community=]
NODE ApplicationDependencyProvider.java [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/dependencies/ApplicationDependencyProvider.java loc=L1 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java loc=L144 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/messages/GroupSendUtil.java loc=L564 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/conversation/ConversationIntents.java loc=L67 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobmanager/Job.java loc=L54 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobManager.java loc=L295 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/OutgoingCallActionProcessor.java loc=L58 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/service/webrtc/IncomingCallActionProcessor.java loc=L60 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/megaphone/Megaphone.java loc=L56 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/sharing/MultiShareArgs.java loc=L122 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/megaphone/Megaphones.java loc=L238 community=]
NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/database/model/MessageRecord.java loc=L401 community=]
... (truncated — 1298 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 6: Test Coverage
**Prompt:** Find the job manager migration logic and its unit tests.

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt:3-68
```java
/**
 * Create a subclass of this to perform a migration on persisted [Job]s. A migration targets
 * a specific end version, and the assumption is that it can migrate jobs to that end version from
 * the previous version. The class will be provided a bundle of job data for each persisted job and
 * give back an updated version (if applicable).
 */
abstract class JobMigration protected constructor(val endVersion: Int) {

  /**
   * Given a bundle of job data, return a bundle of job data that shoul...
```

### [RAG CHUNK] app/src/androidTest/java/org/thoughtcrime/securesms/database/AttachmentTableTest_deduping.kt:512-605
```java
  /**
   * Suite of tests around the migration where we hash all of the attachments and potentially dedupe them.
   */
  @Test
  fun migration() {
    // Verifying that getUnhashedDataFile only returns if there's actually missing hashes
    test {
      val id = insertWithData(DATA_A)
      upload(id)
      assertNull(SignalDatabase.attachments.getUnhashedDataFile())
    }

    // Verifying that getUnhashedDataFile finds the missing hash
    test {
      val id = insertWithData(DATA_A)
      upl...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/components/transfercontrols/TransferControlsContent.kt:92-108
```java
        onPlayClick = onPlayClick
      )

      is TransferControlsRenderState.InProgress -> {
        val cancelLabel = stringResource(android.R.string.cancel)
        val label = state.label
        val progressFormat = stringResource(R.string.TransferControlView__download_progress_s_s)
        val cornerTextReserveWidthFor = (label as? TransferControls.ProgressLabel.Bytes)?.let { byteLabel ->
          val unit = byteLabel.total.getLargestNonZeroSize()
          val widestCompleted = byteLab...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/components/transfercontrols/TransferControlsContent.kt:286-302
```java
  return stringResource(if (isUpload) R.string.TransferControlView__upload else R.string.TransferControlView__download)
}

@Composable
private fun progressLabelText(label: TransferControls.ProgressLabel): String {
  return when (label) {
    is TransferControls.ProgressLabel.Processing -> stringResource(R.string.TransferControlView__processing)
    is TransferControls.ProgressLabel.Bytes -> {
      val unit = label.total.getLargestNonZeroSize()
      stringResource(
        R.string.TransferCont...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['Unit', 'Unit', 'Unit'] | 37 nodes found

NODE remember() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/main/ChatsNavHost.kt loc=L260 community=]
NODE RemoteBackupsSettingsContent() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/settings/app/backups/remote/RemoteBackupsSettingsFragment.kt loc=L357 community=]
NODE InAppPaymentAuthCheckJob [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentAuthCheckJob.kt loc=L39 community=]
NODE IndividualSendJobV2 [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJobV2.kt loc=L74 community=]
NODE BiometricPrompt [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/settings/app/privacy/screenlock/ScreenLockSettingsFragment.kt loc=L72 community=]
NODE rememberBiometricsAuthentication() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/compose/BiometricsAuthentication.kt loc=L54 community=]
NODE .checkRecurringPayment() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentAuthCheckJob.kt loc=L164 community=]
NODE BiometricDeviceLockContract [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/BiometricDeviceAuthentication.kt loc=L112 community=]
NODE .doWork() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJobV2.kt loc=L144 community=]
NODE ChatsSettingsScreen() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/settings/app/chats/ChatsSettingsFragment.kt loc=L137 community=]
NODE .checkOneTimePayment() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentAuthCheckJob.kt loc=L125 community=]
NODE LocalBackupsSettingsScreen() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/components/settings/app/backups/local/LocalBackupsSettingsScreen.kt loc=L47 community=]
NODE .checkResult() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/InAppPaymentAuthCheckJob.kt loc=L282 community=]
NODE .syncPreKeysIfNecessary() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJobV2.kt loc=L481 community=]
NODE .logPrefix() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/jobs/IndividualSendJobV2.kt loc=L514 community=]
... (truncated — 22 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

## Task 7: Deprecation Hunt
**Prompt:** Find deprecated code related to job migrations.

### [Tool: RAG + AST]
### [AST DEF] app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigration.kt:3-68
```java
/**
 * Create a subclass of this to perform a migration on persisted [Job]s. A migration targets
 * a specific end version, and the assumption is that it can migrate jobs to that end version from
 * the previous version. The class will be provided a bundle of job data for each persisted job and
 * give back an updated version (if applicable).
 */
abstract class JobMigration protected constructor(val endVersion: Int) {

  /**
   * Given a bundle of job data, return a bundle of job data that shoul...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/database/helpers/SignalDatabaseMigrations.kt:179-261
```java
/**
 * Contains all of the database migrations for [SignalDatabase]. Broken into a separate file for cleanliness.
 */
object SignalDatabaseMigrations {

  val TAG: String = Log.tag(SignalDatabaseMigrations.javaClass)

  private val migrations: List<Pair<Int, SignalDatabaseMigration>> = listOf(
    149 to V149_LegacyMigrations,
    150 to V150_UrgentMslFlagMigration,
    151 to V151_MyStoryMigration,
    152 to V152_StoryGroupTypesMigration,
    153 to V153_MyStoryMigration,
    154 to V154_PniSi...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/jobmanager/JobMigrator.java:15-31
```java

@SuppressLint("UseSparseArrays")
public class JobMigrator {

  private static final String TAG = Log.tag(JobMigrator.class);

  private final int                        lastSeenVersion;
  private final int                        currentVersion;
  private final Map<Integer, JobMigration> migrations;

  public JobMigrator(int lastSeenVersion, int currentVersion, @NonNull List<JobMigration> migrations) {
    this.lastSeenVersion = lastSeenVersion;
    this.currentVersion  = currentVersion;
    thi...
```

### [RAG CHUNK] app/src/main/java/org/thoughtcrime/securesms/jobs/DeprecatedNotificationJob.kt:22-81
```java
/**
 * Notifies users that their build expired and redirects to the download page on click.
 */
class DeprecatedNotificationJob private constructor(parameters: Parameters) : Job(parameters) {
  companion object {
    const val KEY: String = "DeprecatedNotificationJob"
    private val TAG = Log.tag(DeprecatedNotificationJob::class.java)

    @JvmStatic
    fun enqueue() {
      AppDependencies.jobManager.add(DeprecatedNotificationJob())
    }
  }

  private constructor() : this(
    Parameters.Bu...
```

### [Tool: Graphify]
```
Traversal: BFS depth=2 | Start: ['Deprecated', 'Deprecated', 'Code'] | 70 nodes found

NODE NonNull [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L614 community=]
NODE Nullable [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L277 community=]
NODE Nullable [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/payments/confirm/ConfirmPaymentRepository.java loc=L115 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L187 community=]
NODE Context [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java loc=L57 community=]
NODE TextSecurePreferences [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L45 community=]
NODE Uri [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L614 community=]
NODE WorkerThread [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java loc=L57 community=]
NODE String [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L277 community=]
NODE .toByteArray() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java loc=L243 community=]
NODE .edit() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/groups/GroupManagerV2.java loc=L194 community=]
NODE .getBooleanPreference() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L822 community=]
NODE .createScaledBytes() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java loc=L57 community=]
NODE .getStringPreference() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L830 community=]
NODE BitmapUtil [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/BitmapUtil.java loc=L43 community=]
NODE .setBooleanPreference() [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L818 community=]
NODE Deprecated [src=/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android/app/src/main/java/org/thoughtcrime/securesms/util/TextSecurePreferences.java loc=L268 community=]
... (truncated — 53 more nodes cut by ~1000-token budget. Narrow with context_filter=['call'] or use get_node for a specific symbol)

```

---

