import "dart:math";

class Greeter {
  String hello(String name) {
    return "hello $name";
  }
}

String buildMessage(String name) {
  return Greeter().hello(name);
}
