# Batch 02 metadata repair r1

This versioned derivative repairs only F004-V4 annotations. Its defect category is `ARITHMETIC_FORMULA`, subtype `UNWEIGHTED_MEAN`. The rationale now states that the wrong unweighted mean can diverge from the COBOL weighted mean and that rounding can mask a difference. The family focus remains `DECIMAL_ROUNDING_AND_SCALE`: it describes the family rather than every variant's defect.

`dataset.json` retains every original source line, test, expected output, alignment, split, equivalence flag and proposed/unexecuted label. A deep comparison permits exactly three metadata changes; details, original/derivative hashes and prior runtime evidence hashes are recorded in `changes.json`. Original batch 02 files were preserved. No compilation, program execution or model training was performed for this metadata repair.

The prior runtime report confirms F004-V4 mismatches on T5 (COBOL 16.67, Java 15.00) and T6 (COBOL 10.02, Java 10.01). Its additional A4 case has unequal quantities and prices yet both outputs are 10.01, supporting the corrected bounded rationale. This finite execution evidence does not prove equivalence.
