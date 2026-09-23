-- Headache log dialogs. Called by predict.py --log with:
--   argv 1: day label ("today (Tue 9/22)")
--   argv 2-6: option lists, one per line: meds (first = "None"), triggers, headache
--             types, onsets, symptoms
--   argv 7-14: previous answers when editing a day, "" for a new entry:
--             headache button, type, onset, severity option, symptoms (lines),
--             meds (lines), triggers (lines), notes
-- Returns: headache(true/false) TAB type TAB onset TAB severity TAB symptoms;... TAB meds;...
--          TAB triggers;... TAB notes
-- Cancel anywhere aborts with error -128 and nothing is saved.
-- Note: "kind" is reserved in AppleScript and fails at runtime, hence hType.

on joinList(theList, delim)
	set AppleScript's text item delimiters to delim
	set s to theList as text
	set AppleScript's text item delimiters to ""
	return s
end joinList

on splitLines(txt)
	if txt is "" then return {}
	return paragraphs of txt
end splitLines

-- One place for every list question, so edits can pre-select earlier answers.
on pickFrom(opts, promptText, defs, multi, emptyOK)
	if (count of defs) > 0 then
		set res to choose from list opts with title "Headache log" with prompt promptText ¬
			default items defs multiple selections allowed multi empty selection allowed emptyOK
	else
		set res to choose from list opts with title "Headache log" with prompt promptText ¬
			multiple selections allowed multi empty selection allowed emptyOK
	end if
	if res is false then error number -128
	return res
end pickFrom

on run argv
	set dayLabel to item 1 of argv
	set medsOpts to paragraphs of item 2 of argv
	set trigOpts to paragraphs of item 3 of argv
	set typeOpts to paragraphs of item 4 of argv
	set onsetOpts to paragraphs of item 5 of argv
	set symOpts to paragraphs of item 6 of argv
	set prevButton to item 7 of argv
	set prevType to my splitLines(item 8 of argv)
	set prevOnset to my splitLines(item 9 of argv)
	set prevSev to my splitLines(item 10 of argv)
	set prevSym to my splitLines(item 11 of argv)
	set prevMeds to my splitLines(item 12 of argv)
	set prevTrig to my splitLines(item 13 of argv)
	set prevNotes to item 14 of argv
	if prevButton is "" then set prevButton to "Headache"
	if (count of prevType) is 0 then set prevType to {item -1 of typeOpts}
	if (count of prevOnset) is 0 then set prevOnset to {item 1 of onsetOpts}
	if (count of prevSev) is 0 then set prevSev to {"4 - distracting"}
	if (count of prevMeds) is 0 then set prevMeds to {item 1 of medsOpts}
	activate

	set r to display dialog "Headache " & dayLabel & "?" buttons {"Cancel", "No headache", "Headache"} ¬
		default button prevButton cancel button "Cancel" with title "Headache log"
	set hasHeadache to (button returned of r is "Headache")

	set hType to ""
	set onset to ""
	set sev to ""
	set symPick to {}
	if hasHeadache then
		set hType to item 1 of my pickFrom(typeOpts, "What kind was it?", prevType, false, false)
		set onset to item 1 of my pickFrom(onsetOpts, "When did it start?", prevOnset, false, false)
		set sevOpts to {"1 - barely noticeable", "2", "3", "4 - distracting", "5", "6", ¬
			"7 - hard to function", "8", "9", "10 - worst ever"}
		set sevPick to my pickFrom(sevOpts, "How bad was it at its worst?", prevSev, false, false)
		set sev to word 1 of (item 1 of sevPick)
		set symPick to my pickFrom(symOpts, "Any other symptoms? (⌘-click to pick several, or none)", ¬
			prevSym, true, true)
	end if

	set medsPick to my pickFrom(medsOpts, "Any meds " & dayLabel & "? (⌘-click to pick several)", ¬
		prevMeds, true, false)
	set trigPick to my pickFrom(trigOpts, ¬
		"Anything that might have played a part? (⌘-click to pick several, or none)", ¬
		prevTrig, true, true)

	set noteR to display dialog "Notes (optional):" default answer prevNotes with title "Headache log" ¬
		buttons {"Cancel", "Save"} default button "Save" cancel button "Cancel"

	return (hasHeadache as text) & tab & hType & tab & onset & tab & sev & tab & ¬
		joinList(symPick, ";") & tab & joinList(medsPick, ";") & tab & joinList(trigPick, ";") & tab & ¬
		(text returned of noteR)
end run
