# Step 2 (not implemented)

Do not add these until step 1 has been run on the target PC.

- Echo: after a real transcript, flag `echo` when a later transcript within a few seconds is the same phrase. Do not compare an utterance to itself.
- Idle speech: flag `idle-speech` when a transcript arrives while Windows last-input time is past the idle window, or while a configured push-to-talk key is not held. Use `GetLastInputInfo` on Windows only. If that API is unavailable, leave the flag off and say so.
- Speaker match: WASAPI loopback capture already exists as `source_mode = "system"` (or `"both"`). Compare the loopback stream to the microphone and flag `loopback` only when both sides have energy and the match score clears a documented threshold. Add that comparison in this step, not before.
- Clips: once flags exist, save WAVs for flagged rows rather than every transcript.

No flag may be written unless the comparison above actually ran on captured samples.
