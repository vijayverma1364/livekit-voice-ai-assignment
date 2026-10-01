Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile("test_speech.wav")
$synth.Speak("Hello, I need help with my account. Can you check my order?")
$synth.Dispose()
Write-Host "Generated test_speech.wav successfully!"
