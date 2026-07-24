use std::fmt::Display;

pub struct Greeter;

impl Greeter {
    pub fn hello<T: Display>(&self, name: T) -> String {
        format!("hello {name}")
    }
}

pub fn build_message(name: &str) -> String {
    Greeter.hello(name)
}
