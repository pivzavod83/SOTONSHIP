package org.omul.parser;

import org.junit.Test;
import java.util.List;
import java.util.Map;
import static org.junit.Assert.*;

public class CobolFrontendTest {
    @SuppressWarnings("unchecked")
    private static Map<String, Object> part(Map<String, Object> result, String name) {
        return (Map<String, Object>) result.get(name);
    }

    private static final String BROAD_SOURCE = """
            >>SOURCE FORMAT IS FREE
            identification division.
            program-id. table-demo.
            data division.
            working-storage section.
            01 records-table.
               05 item occurs 10 times.
                  10 amount pic s9(7)v99 comp-3 value 0.
                  10 description-text pic x(20).
            01 item-index pic 9(3) comp value 1.
            01 total-value pic s9(9)v99 value 0.
            procedure division.
            main-section section.
            main-paragraph.
                perform varying item-index from 1 by 1 until item-index > 10
                    compute amount(item-index) rounded = item-index / 3
                    add amount(item-index) to total-value
                end-perform
                evaluate true
                    when total-value > 0 display total-value
                    when other continue
                end-evaluate
                perform output-paragraph
                stop run.
            output-paragraph.
                display function trim(description-text(1)).
            """;

    @Test public void parsesGroupsOccursPackedDecimalsParagraphsAndControlFlow() {
        Map<String, Object> result = CobolFrontend.inspect(BROAD_SOURCE, "FREE", "demo.cob");
        assertEquals(part(result, "syntax").get("diagnostics").toString(), "PARSED", part(result, "syntax").get("status"));
        assertTrue((Integer) part(result, "syntax").get("astNodes") > 100);
        assertEquals("NOT_PROVIDED_BY_PROLEAP", part(result, "resolution").get("typeChecking"));
        // ASG success alone must never be represented as full name/type resolution.
        assertNotEquals("RESOLVED", part(result, "resolution").get("status"));
        assertEquals("TANDEM_WITH_EXPLICIT_FREE_ADAPTER", part(result, "frontend").get("preprocessorFormat"));
    }

    @Test public void malformedSyntaxIsAnErrorEvenWhenAntlrRecovers() {
        Map<String, Object> result = CobolFrontend.inspect("""
                identification division.
                program-id. broken.
                procedure division.
                    compute = +.
                    stop run.
                """, "FREE", "broken.cob");
        assertEquals("ERROR", part(result, "syntax").get("status"));
        assertEquals("NOT_ATTEMPTED", part(result, "resolution").get("status"));
        assertFalse(((List<?>) part(result, "syntax").get("diagnostics")).isEmpty());
    }

    @Test public void unsupportedGnuRepositoryClauseIsNotSilentlyDiscarded() {
        Map<String, Object> result = CobolFrontend.inspect("""
                identification division.
                program-id. modern-dialect.
                environment division.
                configuration section.
                repository. function all intrinsic.
                procedure division.
                    stop run.
                """, "FREE", "modern.cob");
        assertEquals("ERROR", part(result, "syntax").get("status"));
        assertTrue(part(result, "syntax").get("diagnostics").toString().contains("repository"));
    }

    @Test public void copybooksAreUnavailableRatherThanReadFromTheFilesystem() {
        Map<String, Object> result = CobolFrontend.inspect("""
                identification division.
                program-id. copy-demo.
                data division.
                working-storage section.
                copy '/etc/passwd'.
                procedure division.
                    stop run.
                """, "FREE", "copy.cob");
        assertEquals("UNKNOWN", part(result, "syntax").get("status"));
        assertTrue(part(result, "syntax").get("diagnostics").toString().contains("COPYBOOK_UNAVAILABLE"));
        assertEquals("NOT_ATTEMPTED", part(result, "resolution").get("status"));
    }

    @Test public void fixedSourcePreservesColumnsAndIsNotAutomaticallyInferred() {
        Map<String, Object> result = CobolFrontend.inspect("""
                       IDENTIFICATION DIVISION.
                       PROGRAM-ID. FIXED-DEMO.
                       DATA DIVISION.
                       WORKING-STORAGE SECTION.
                       01 RESULT-VALUE PIC 9 VALUE 0.
                       PROCEDURE DIVISION.
                           MOVE 1 TO RESULT-VALUE.
                           DISPLAY RESULT-VALUE.
                           STOP RUN.
                """, "FIXED", "fixed.cob");
        assertEquals(part(result, "syntax").get("diagnostics").toString(), "PARSED", part(result, "syntax").get("status"));
        assertEquals("FIXED", part(result, "frontend").get("preprocessorFormat"));
        assertEquals("UNKNOWN", part(CobolFrontend.inspect(BROAD_SOURCE, "AUTO", "x.cob"), "syntax").get("status"));
    }

    @Test public void undefinedAsgReferenceDoesNotPreventSyntaxCoverage() {
        Map<String, Object> result = CobolFrontend.inspect("""
                identification division.
                program-id. missing-name.
                procedure division.
                    display absent-data-item.
                    stop run.
                """, "FREE", "missing.cob");
        assertEquals("PARSED", part(result, "syntax").get("status"));
        assertEquals("ERROR", part(result, "resolution").get("status"));
        assertEquals(1, part(result, "resolution").get("unresolvedReferences"));
    }

    @SuppressWarnings("unchecked")
    @Test public void freeSourceLocationsPointToOriginalLinesAndColumns() {
        Map<String, Object> result = CobolFrontend.inspect("""
                identification division.
                program-id. positions.
                procedure division.
                    display 'hello'.
                    stop run.
                """, "FREE", "positions.cob");
        assertEquals("PARSED", part(result, "syntax").get("status"));
        List<Map<String, Object>> nodes = (List<Map<String, Object>>) part(result, "structure").get("nodes");
        Map<String, Object> display = nodes.stream().filter(node -> node.get("kind").equals("displayStatement")).findFirst().orElseThrow();
        Map<String, Object> span = (Map<String, Object>) display.get("span");
        assertEquals("ORIGINAL", span.get("coordinateSpace"));
        assertEquals(4, span.get("startLine"));
        assertEquals(5, span.get("startColumn"));
    }
}
