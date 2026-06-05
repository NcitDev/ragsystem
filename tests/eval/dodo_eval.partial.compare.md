# Dodo RAG vs Grep Tool Eval

- Repo: `dodo`
- Source root: `/Users/nikitaf/development/projects/dodo-mobile-android/project`
- Top K: **10**
- Tasks: **7**
- RAG avg recall / MRR: **0.095 / 0.190**
- Grep avg recall / MRR: **0.762 / 0.738**
- RAG p50 latency: **13999 ms**; grep+read p50 latency: **304 ms**
- Avg approximate tokens returned: RAG **1630**, grep+read **12077**
- Avg token reduction from RAG chunks: **77%**
- Pass rate: RAG **0%**, grep **71%**

Token counts are a proxy: `chars / 4`. The grep baseline reads full candidate files because that is the expensive tool behavior RAG is meant to avoid.

| Task | RAG recall | Grep recall | RAG rank | Grep rank | RAG tok | Grep tok | Saved |
|------|------------|-------------|----------|-----------|---------|----------|-------|
| dodo-1-card-payment-presenter | 0.33 | 0.67 | 3 | 2 | 1983 | 19171 | 90% |
| dodo-2-wait-for-paid-order | 0.33 | 1.00 | 1 | 1 | 1957 | 25570 | 92% |
| dodo-3-phone-formatting | 0.00 | 1.00 | - | 1 | 1056 | 3043 | 65% |
| dodo-4-google-map-checkout-camera | 0.00 | 0.67 | - | 3 | 3446 | 6198 | 44% |
| dodo-5-pizzeria-cluster-map | 0.00 | 0.75 | - | 1 | 1 | 9640 | 100% |
| dodo-6-cache-validity | 0.00 | 1.00 | - | 1 | 1960 | 4447 | 56% |
| dodo-7-coroutine-presentation-base | 0.00 | 0.25 | - | 3 | 1005 | 16469 | 94% |

## Per-task Results

### dodo-1-card-payment-presenter
- Query: `card payment presenter handles PaymentAuthorization success 3DS failure cancel and returns card payment result`
- Expected: ['context/order/src/main/java/com/dodopizza/order/feature/payment/card/presentation/CardPaymentPresenter.kt', 'context/order/src/main/java/com/dodopizza/order/feature/payment/card/presentation/CardPaymentInteractor.kt', 'context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt']
- RAG matched: ['context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt']
- Grep matched: ['context/order/src/main/java/com/dodopizza/order/feature/payment/card/presentation/CardPaymentPresenter.kt', 'context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt']
- RAG files:
  1. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/PaymentAuthorizationResult.kt`
  2. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenCreateOrderPressed.kt`
  3. `context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt`
  4. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/PaymentAuthorizationResult.kt`
  5. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/Confirm3DSResult.kt`
  6. `context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt`
  7. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenChargeBySavedCardPayment.kt`
  9. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenCreateOrderPressed.kt`
  10. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/Confirm3DSResult.kt`
  11. `context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt`
  12. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt`
  13. `context/order/src/test/java/com/dodopizza/order/feature/payment/secure3d/Secure3dPresenterTest.kt`
  14. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenChargeBySavedCardPayment.kt`
  15. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/dsl/Create.kt`
  16. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenCreateOrderPressed.kt`
  17. `context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt`
- Grep files:
  1. `context/order/detekt-baseline.xml`
  2. `context/order/src/main/java/com/dodopizza/order/feature/payment/card/presentation/CardPaymentPresenter.kt`
  3. `context/order/src/main/java/com/dodopizza/order/feature/payment/card/presentation/CardPaymentFragment.kt`
  4. `context/order/src/main/java/com/dodopizza/order/feature/payment/card/di/CardPaymentModule.kt`
  5. `context/order/src/main/java/com/dodopizza/order/feature/payment/card/di/CardPaymentComponent.kt`
  6. `context/order/src/main/java/com/dodopizza/order/feature/payment/webviewcard/presentation/WebViewCardPaymentFragment.kt`
  7. `context/order/src/main/java/com/dodopizza/order/feature/payment/webviewcard/presentation/WebViewCardPaymentPresenter.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/payment/card/CardPaymentPresenterTests.kt`
  9. `infrastracture/payment/src/main/java/com/dodopizza/payment/PaymentServiceFacade.kt`
  10. `infrastracture/payment/src/main/java/com/dodopizza/payment/impl/card/network/PaymentAuthorize.kt`

### dodo-2-wait-for-paid-order
- Query: `wait for paid order service converts PaidOrderResponse to CreatedOrder WorkflowAlreadyChanged Failure and setupAppStateForNewOrder`
- Expected: ['context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderService.kt', 'context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/PaidOrderResponseVO.kt', 'context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt']
- RAG matched: ['context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt']
- Grep matched: ['context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderService.kt', 'context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/PaidOrderResponseVO.kt', 'context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt']
- RAG files:
  1. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  2. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  3. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  4. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  5. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  6. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt`
  7. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  9. `context/order/src/test/java/com/dodopizza/order/domain/workflow/checkout/dsl/CreateCheckoutService.kt`
  10. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  11. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt`
  12. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/CheckoutStateLogic.kt`
  13. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  14. `context/order/src/test/java/com/dodopizza/order/feature/checkout/dsl/CreateCheckoutState.kt`
  15. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/CheckoutStateLogic.kt`
  16. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/dsl/CreateCheckoutState.kt`
  17. `context/order/src/test/java/com/dodopizza/order/feature/foodmenu/ordertypeswitcher/presentation/WhenFirstViewAttach_ifAppIsNotInitialized.kt`
  18. `context/order/src/test/java/com/dodopizza/order/feature/shoppingcart/dsl/StateBuilder.kt`
  19. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/CheckoutStateLogic.kt`
- Grep files:
  1. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderService.kt`
  2. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/di/MainScreenModule.kt`
  3. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/WaitForPaidOrderServiceImplTest.kt`
  4. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/MainScreenPresenterTest.kt`
  5. `context/order/src/test/java/com/dodopizza/order/feature/mainscreen/presentation/MainScreenInteractorTest.kt`
  6. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/PaidOrderResponseVO.kt`
  7. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/MainScreenPresenter.kt`
  8. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/MainScreenInteractor.kt`
  9. `context/order/src/main/java/com/dodopizza/order/domain/workflow/checkout/CheckoutService.kt`
  10. `context/core/src/main/java/com/dodopizza/core/domain/state/StateAnalyzer.kt`

### dodo-3-phone-formatting
- Query: `phone number formatting detect phone format parse input handler default phone format provider`
- Expected: ['infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatService.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatDetector.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneParserImplementation.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneInputHandlerImplementation.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/DefaultPhoneFormatProvider.kt']
- RAG matched: []
- Grep matched: ['infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatService.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatDetector.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneParserImplementation.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneInputHandlerImplementation.kt', 'infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/DefaultPhoneFormatProvider.kt']
- RAG files:
  1. `infrastracture/infrastructure-base/src/main/java/ru/dodopizza/app/infrastracture/utils/TextHelper.java`
  2. `infrastracture/infrastructure-base/src/main/java/ru/dodopizza/app/infrastracture/utils/TextHelper.java`
  3. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/textview/DodoInputText.java`
  4. `context/order/src/test/java/com/dodopizza/order/feature/checkout/Create.kt`
  5. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/textview/DodoInputAutocompleteText.java`
  6. `context/order/src/test/java/com/dodopizza/order/feature/checkout/deferredtime/DeferredTimeFormatterIntervalTest.kt`
  7. `context/order/src/main/java/com/dodopizza/order/feature/promopickmodal/di/PromoPickModalModule.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/dsl/Create.kt`
  9. `context/order/src/test/java/com/dodopizza/order/feature/shoppingcart/dsl/Create.kt`
  10. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/textview/DodoInputAutocompleteText.java`
- Grep files:
  1. `infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/DefaultPhoneFormatProvider.kt`
  2. `infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatService.kt`
  3. `infrastracture/phonenumber/src/test/java/com/dodopizza/phonenumber/Create.kt`
  4. `infrastracture/phonenumber/detekt-baseline.xml`
  5. `infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneFormatDetector.kt`
  6. `infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneParserImplementation.kt`
  7. `infrastracture/phonenumber/src/main/java/com/dodopizza/phonenumber/format/PhoneInputHandlerImplementation.kt`

### dodo-4-google-map-checkout-camera
- Query: `google maps checkout map view controller moves and animates camera from CameraConfiguration to CameraPosition`
- Expected: ['infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/checkout/CheckoutMapViewController.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/utils/CoordinatesUtils.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/MapController.kt']
- RAG matched: []
- Grep matched: ['infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/checkout/CheckoutMapViewController.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/utils/CoordinatesUtils.kt']
- RAG files:
  1. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/OtherCheckoutDetailsPresenterTests.kt`
  2. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/details/views/DestinationView.kt`
  3. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenAddressViewPressed.kt`
  4. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/details/views/AddressView.kt`
  5. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/details/views/OrderTypeView.kt`
  6. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/OtherCheckoutDetailsPresenterTests.kt`
  7. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenAddressViewPressed.kt`
  8. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/details/views/OrderTypeView.kt`
  9. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/WhenAddressViewPressed.kt`
  10. `context/order/src/main/java/ru/dodopizza/app/presentation/checkout/details/views/PizzeriaView.kt`
  11. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/circleimageview/CircleAnimationUtil.java`
  12. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/circleimageview/CircleAnimationUtil.java`
  13. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/scene/common/AnchorNodeModel.kt`
  14. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/circleimageview/CircleAnimationUtil.java`
  15. `context/order/src/main/java/com/dodopizza/order/feature/promopickmodal/presentation/PromoPickModalFragment.kt`
  16. `context/order/src/main/java/com/dodopizza/order/feature/promopickmodal/presentation/PromoPickModalView.kt`
  17. `ar_dynamic/src/main/kotlin/ru/dodopizza/wave/ArWaveAnimation.kt`
  18. `context/order/src/main/java/com/dodopizza/order/feature/promopickmodal/presentation/PromoPickModalView.kt`
  19. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/CameraPermissionViewModel.kt`
  20. `infrastracture/android/src/main/java/com/dodopizza/android/view/custom/circleimageview/CircleAnimationUtil.java`
- Grep files:
  1. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/checkout/CheckoutMapViewController.kt`
  2. `app/src/prodHuawei/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  3. `infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/checkout/CheckoutMapViewController.kt`
  4. `app/src/betaHuawei/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  5. `app/src/prod/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  6. `app/src/beta/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  7. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/utils/CoordinatesUtils.kt`
  8. `infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/utils/CoordinatesUtils.kt`
  9. `infrastracture/maps/src/main/java/com/dodopizza/maps/ordersummary/OrderSummaryMapController.kt`
  10. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/ordersummary/OrderSummaryMapViewController.kt`

### dodo-5-pizzeria-cluster-map
- Query: `pizzeria selection map cluster manager renderer cluster factory select unselect pizzeria markers`
- Expected: ['infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/selectionmap/PizzeriasClusterMapController.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/PizzeriasRender.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/ClusterFactory.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/PizzeriaClusterModel.kt']
- RAG matched: []
- Grep matched: ['infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/selectionmap/PizzeriasClusterMapController.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/PizzeriasRender.kt', 'infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/ClusterFactory.kt']
- RAG files:
- Grep files:
  1. `infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/selectionmap/PizzeriasClusterMapController.kt`
  2. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/selectionmap/PizzeriasClusterMapController.kt`
  3. `app/src/prodHuawei/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  4. `app/src/betaHuawei/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  5. `app/src/beta/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  6. `app/src/prod/java/ru/dodopizza/app/selectlocation/di/MapModule.kt`
  7. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/PizzeriasRender.kt`
  8. `infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/PizzeriasRender.kt`
  9. `infrastracture/huaweimaps/src/main/java/com/dodopizza/huaweimaps/ClusterFactory.kt`
  10. `infrastracture/googlemaps/src/main/java/com/dodopizza/googlemaps/ClusterFactory.kt`

### dodo-6-cache-validity
- Query: `cache inspector validates timestamp expiration invalidates cache keys and cacheable service reloads invalid cache`
- Expected: ['infrastracture/cache/src/main/java/com/dodopizza/cache/CacheInspector.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheableService.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheTimestampRepository.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheParams.kt']
- RAG matched: []
- Grep matched: ['infrastracture/cache/src/main/java/com/dodopizza/cache/CacheInspector.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheableService.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheTimestampRepository.kt', 'infrastracture/cache/src/main/java/com/dodopizza/cache/CacheParams.kt']
- RAG files:
  1. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/MoneyInputValidatorTest.kt`
  2. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/MoneyInputValidatorTest.kt`
  3. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/files/ArModelFilesStorage.kt`
  4. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/MoneyInputValidatorTest.kt`
  5. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/MoneyInputValidatorTest.kt`
  6. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/FloatMoneyInputValidatorTest.kt`
  7. `context/order/src/test/java/com/dodopizza/order/feature/collaboration/CollaborationPromoPresenterTest.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/FloatMoneyInputValidatorTest.kt`
  9. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/FloatMoneyInputValidatorTest.kt`
  10. `context/order/src/test/java/com/dodopizza/order/feature/checkout/cashcharge/validation/FloatMoneyInputValidatorTest.kt`
  11. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/WhenSelectCarryoutPizzeria.kt`
  12. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/WhenSelectRestaurantPizzeria.kt`
  13. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/WhenSelectDeliverablePlaceTest.kt`
  14. `context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/WhenSwitchToDelivery.kt`
  15. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/avatar/ProfileDisplayInfoInteractor.kt`
  16. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/ArSupportChecker.kt`
  17. `ar_dynamic/src/main/kotlin/ru/dodopizza/wave/ArWaveWelcomeAnimationState.kt`
  18. `context/order/src/test/java/com/dodopizza/order/domain/OrderManagerImplTest.kt`
  19. `context/order/src/test/java/com/dodopizza/order/domain/OrderManagerImplTest.kt`
- Grep files:
  1. `infrastracture/cache/src/main/java/com/dodopizza/cache/CacheInspector.kt`
  2. `app/src/main/java/ru/dodopizza/app/di/modules/DataSourceModule.kt`
  3. `context/onboarding/src/main/java/com/dodopizza/onboarding/domain/landing/LandingService.kt`
  4. `domain/base/src/main/java/ru/dodopizza/app/domain/country/AddressDetailsFieldDesignService.kt`
  5. `infrastracture/cache/src/main/java/com/dodopizza/cache/CacheableService.kt`
  6. `context/order/src/main/java/com/dodopizza/order/domain/workflow/checkout/CheckoutService.kt`
  7. `infrastracture/cache/src/main/java/com/dodopizza/cache/CacheTimestampRepository.kt`
  8. `domain/base/src/main/java/ru/dodopizza/app/domain/cache/CacheTimestampRepositoryImpl.kt`
  9. `infrastracture/cache/src/main/java/com/dodopizza/cache/CacheParams.kt`

### dodo-7-coroutine-presentation-base
- Query: `base presenter and base view model coroutine scopes attach detach clear view model job cancellation`
- Expected: ['infrastracture/presentation/src/main/java/com/dodopizza/presentation/presenters/BasePresenter.kt', 'infrastracture/presentation/src/main/java/com/dodopizza/presentation/lifecycle/BaseViewModel.kt', 'infrastracture/presentation/src/main/java/com/dodopizza/presentation/CoroutineContextTools.kt', 'infrastracture/coroutines-utils/src/main/java/com/dodopizza/coroutines/utils/debounce.kt']
- RAG matched: []
- Grep matched: ['infrastracture/presentation/src/main/java/com/dodopizza/presentation/presenters/BasePresenter.kt']
- RAG files:
  1. `context/order/src/test/java/com/dodopizza/order/feature/foodmenu/presentation/BaseFoodMenuPresentersTests.kt`
  2. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/BaseCheckoutDetailsPresenterTests.kt`
  3. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/arch/ViewModel.kt`
  4. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/arch/ViewModel.kt`
  5. `context/order/src/test/java/com/dodopizza/order/feature/product/card/presentation/product/ProductCardPresenterTest.kt`
  6. `context/order/src/test/java/com/dodopizza/order/feature/foodmenu/presentation/BaseFoodMenuPresentersTests.kt`
  7. `context/order/src/test/java/com/dodopizza/order/feature/promoaction/presentation/BaseSpecialOfferDialogPresenterTest.kt`
  8. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/BaseCheckoutDetailsPresenterTests.kt`
  9. `context/order/src/test/java/com/dodopizza/order/feature/foodmenu/ordertypeswitcher/presentation/BaseOrderTypeSwitcherPresenterTest.kt`
  10. `context/order/src/test/java/com/dodopizza/order/feature/checkout/details/presentation/SbpBankListPresenterTest.kt`
  11. `context/order/src/test/java/com/dodopizza/order/feature/foodmenu/presentation/OtherFoodMenuPresenterTests.kt`
  12. `context/order/src/test/java/com/dodopizza/order/feature/promoaction/presentation/BaseSpecialOfferDialogPresenterTest.kt`
  13. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/ShareButtonViewModel.kt`
  14. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/arch/ViewModel.kt`
  15. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/CameraPermissionViewModel.kt`
  16. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/scene/arch/ModelCoroutineScope.kt`
  17. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/CameraPermissionViewModel.kt`
  18. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/ArPizzaViewModel.kt`
  19. `context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/chat/MainHeaderChatPresenter.kt`
  20. `ar_dynamic/src/main/kotlin/ru/dodopizza/ar/compose/ShareButtonViewModel.kt`
- Grep files:
  1. `infrastracture/lint-checks/src/main/java/com/dodopizza/lint/PresentationLayerDetector.kt`
  2. `wiki/architecture-notification-permissions.md`
  3. `infrastracture/presentation/src/main/java/com/dodopizza/presentation/presenters/BasePresenter.kt`
  4. `infrastracture/statemachine/src/main/java/com/dodopizza/presentation/presenters/MoxyFSMPresenter.kt`
  5. `app/src/main/java/ru/dodopizza/app/presentation/main/MainActivityPresenter.kt`
  6. `context/onboarding/src/main/java/com/dodopizza/onboarding/feature/chooseordertype/presentation/GeoChooseOrderTypePresenter.kt`
  7. `context/feature-base/src/main/java/com/dodopizza/feature/webinfo/presentation/WebInfoPresenter.kt`
  8. `context/onboarding/src/main/java/com/dodopizza/onboarding/feature/selectlocation/presentation/SelectLocationPresenter.kt`
  9. `context/feature-base/src/main/java/com/dodopizza/feature/imagepicker/presentation/FilePickerDialogPresenter.kt`
  10. `context/loyalty/src/main/java/com/dodopizza/loyalty/missions/presentation/LoyaltyMissionDetailsPresenter.kt`
