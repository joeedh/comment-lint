[x]: if --limit is absent it should assume no limits
[x]: we should support reporting false positives to the ledger as well as false negatives
[x]: rename --file to --entire-file 
[x]: add a command line argument to list rules and what they do
[x]: the rule columns should show 'ruleX' instead of 'PX'
[x]: add a non-model analytical rule (C13) that rejects comments with non-Latin-1 unicode, with a config whitelist for individual codepoints and ranges
[x]: add a --init command line argument that writes a default .commentlintrc.json with every option present, commented out, and explained
