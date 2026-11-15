package main

// Public builds use the demo key. Private release builds replace this file
// through a temporary Go overlay; private generated material never enters Git.
func embeddedAPIKey() string {
	return "7QwA7931lJSQfMKuTH4MQXLn4YEiNhE5tggnYKlY4HE"
}
