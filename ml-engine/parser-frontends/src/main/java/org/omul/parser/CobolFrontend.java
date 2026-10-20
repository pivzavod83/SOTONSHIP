package org.omul.parser;

import io.proleap.cobol.CobolLexer;
import io.proleap.cobol.CobolParser;
import io.proleap.cobol.asg.metamodel.ASGElement;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.call.Call;
import io.proleap.cobol.asg.metamodel.impl.ProgramImpl;
import io.proleap.cobol.asg.metamodel.registry.ASGElementRegistry;
import io.proleap.cobol.asg.metamodel.registry.impl.ASGElementRegistryImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.visitor.impl.CobolCompilationUnitVisitorImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import io.proleap.cobol.preprocessor.impl.CobolPreprocessorImpl;
import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;
import org.antlr.v4.runtime.Token;
import org.antlr.v4.runtime.tree.ParseTree;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Grammar coverage and limited ProLeap binding inspection; never an equivalence proof. */
public final class CobolFrontend {
    public static final String VERSION = "4.0.0";
    public static final String UPSTREAM_COMMIT = "d1bfe75bdd6d480f70c74c6345bcc02610ac30d3";
    private static final int NODE_LIMIT = 500;
    private static final int DIAGNOSTIC_LIMIT = 100;
    private static final Pattern FREE_DIRECTIVE = Pattern.compile(
            "(?i)^\\s*>>\\s*SOURCE\\s+FORMAT\\s+(?:IS\\s+)?[\"']?FREE[\"']?\\s*\\.?\\s*(?:\\*>.*)?$");
    private static final Pattern LINE_NUMBER = Pattern.compile("(?i)line\\s+(\\d+)(?::(\\d+))?");

    private CobolFrontend() { }

    public static Map<String, Object> inspect(String source, String sourceFormat, String virtualFilename) {
        Map<String, Object> result = new LinkedHashMap<>();
        List<Map<String, Object>> diagnostics = new ArrayList<>();
        Map<String, Object> syntax = new LinkedHashMap<>();
        Map<String, Object> resolution = new LinkedHashMap<>();
        Map<String, Object> structure = new LinkedHashMap<>();
        String formatName = sourceFormat == null ? "UNKNOWN" : sourceFormat.toUpperCase(Locale.ROOT);
        result.put("language", "COBOL");
        result.put("frontend", Map.of("name", "ProLeap ANTLR4", "version", VERSION,
                "upstreamCommit", UPSTREAM_COMMIT, "profile", formatName,
                "dialect", "ProLeap COBOL grammar; compiler dialect not inferred",
                "preprocessorFormat", formatName.equals("FREE") ? "TANDEM_WITH_EXPLICIT_FREE_ADAPTER" : formatName));
        syntax.put("status", "UNKNOWN");
        syntax.put("diagnostics", diagnostics);
        syntax.put("astNodes", 0);
        resolution.put("status", "NOT_ATTEMPTED");
        resolution.put("resolvedReferences", null);
        resolution.put("unresolvedReferences", null);
        resolution.put("typeChecking", "NOT_PROVIDED_BY_PROLEAP");
        resolution.put("basis", "ProLeap ASG bindings are partial name resolution, not compiler type checking.");
        resolution.put("diagnostics", new ArrayList<Map<String, Object>>());
        structure.put("nodes", List.of());
        structure.put("nodeCounts", Map.of());
        structure.put("nodeLimit", NODE_LIMIT);
        result.put("syntax", syntax);
        result.put("resolution", resolution);
        result.put("structure", structure);

        if (!Set.of("FREE", "FIXED", "VARIABLE", "TANDEM").contains(formatName)) {
            diagnostics.add(diagnostic("SOURCE_FORMAT_REQUIRED", "Specify FREE, FIXED, VARIABLE or TANDEM; source format is not inferred.", null, null, "ERROR"));
            return result;
        }

        CobolParserParamsImpl params = new CobolParserParamsImpl();
        params.setFormat(formatName.equals("FREE") ? CobolSourceFormatEnum.TANDEM : CobolSourceFormatEnum.valueOf(formatName));
        params.setIgnoreSyntaxErrors(false);
        // Inspect String input only. Empty allowlists prevent all filesystem COPY searches.
        params.setCopyBookDirectories(Collections.emptyList());
        params.setCopyBookFiles(Collections.emptyList());
        params.setCopyBookExtensions(Collections.emptyList());
        String adapted = formatName.equals("FREE") ? adaptFreeSource(source) : source;
        String preprocessed;
        try {
            preprocessed = new CobolPreprocessorImpl().process(adapted, params);
        } catch (RuntimeException e) {
            String message = safeMessage(e);
            boolean dependency = message.toLowerCase(Locale.ROOT).contains("copy book");
            syntax.put("status", dependency ? "UNKNOWN" : "ERROR");
            Integer[] position = errorPosition(message);
            diagnostics.add(diagnostic(dependency ? "COPYBOOK_UNAVAILABLE" : "PREPROCESSOR_ERROR", message, position[0], position[1], "ERROR"));
            return result;
        }

        boolean exactLineMapping = mappingIsSafe(source, preprocessed, formatName);
        structure.put("sourceMapping", exactLineMapping ? "ORIGINAL_VERIFIED_PER_TOKEN" : "PREPROCESSED_ONLY");
        structure.put("preprocessedLineCount", preprocessed.split("\\R", -1).length);
        CobolLexer lexer = new CobolLexer(CharStreams.fromString(preprocessed));
        CollectingErrors listener = new CollectingErrors(diagnostics, formatName, exactLineMapping);
        lexer.removeErrorListeners();
        lexer.addErrorListener(listener);
        CommonTokenStream tokens = new CommonTokenStream(lexer);
        CobolParser parser = new CobolParser(tokens);
        parser.removeErrorListeners();
        parser.addErrorListener(listener);
        CobolParser.StartRuleContext tree;
        try {
            tree = parser.startRule();
            tokens.fill();
        } catch (RuntimeException e) {
            syntax.put("status", "ERROR");
            diagnostics.add(diagnostic("PARSER_ERROR", safeMessage(e), null, null, "ERROR"));
            return result;
        }

        List<Map<String, Object>> nodes = new ArrayList<>();
        Map<String, Integer> counts = new LinkedHashMap<>();
        int ruleNodes = inspectTree(tree, nodes, counts, formatName, exactLineMapping);
        syntax.put("astNodes", ruleNodes);
        syntax.put("tokens", tokens.size());
        syntax.put("status", diagnostics.isEmpty() ? "PARSED" : "ERROR");
        structure.put("nodes", nodes);
        structure.put("nodeCounts", counts);
        structure.put("truncated", ruleNodes > nodes.size());
        structure.put("grammar", "ProLeap Cobol.g4 startRule with EOF; recovered trees do not count as parsed.");
        if (!diagnostics.isEmpty()) return result;

        TrackingProgram program = new TrackingProgram();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> bindingDiagnostics = (List<Map<String, Object>>) resolution.get("diagnostics");
        boolean analysisCompleted = false;
        try {
            String name = virtualFilename == null ? "Input" : virtualFilename.replaceAll(".*[/\\\\]", "").replaceFirst("\\.[^.]*$", "");
            new CobolCompilationUnitVisitorImpl(name, preprocessed.lines().toList(), tokens, program).visit(tree);
            new ExposedRunner().analyzeExisting(program);
            analysisCompleted = true;
        } catch (RuntimeException e) {
            bindingDiagnostics.add(diagnostic("ASG_ANALYSIS_FAILED", safeMessage(e), null, null, "ERROR"));
        }
        int resolved = 0;
        int unresolved = 0;
        Map<String, Integer> callTypes = new LinkedHashMap<>();
        List<Map<String, Object>> symbols = new ArrayList<>();
        Set<Call> seenCalls = Collections.newSetFromMap(new IdentityHashMap<>());
        for (ASGElement element : program.registry.elements) {
            if (!(element instanceof Call call)) continue;
            Call unwrapped = call.unwrap();
            if (unwrapped != null && !seenCalls.add(unwrapped)) continue;
            String kind = unwrapped == null ? "UNDEFINED_CALL" : unwrapped.getCallType().name();
            callTypes.merge(kind, 1, Integer::sum);
            if (kind.equals("UNDEFINED_CALL")) {
                unresolved++;
                if (bindingDiagnostics.size() < DIAGNOSTIC_LIMIT) {
                    Map<String, Object> span = span(element.getCtx(), formatName, exactLineMapping);
                    bindingDiagnostics.add(diagnostic("UNRESOLVED_ASG_REFERENCE", "ProLeap could not bind reference: " + call.getName(),
                            (Integer) span.get("startLine"), (Integer) span.get("startColumn"), "ERROR"));
                }
            } else resolved++;
            if (symbols.size() < NODE_LIMIT) {
                Map<String, Object> symbol = new LinkedHashMap<>();
                symbol.put("name", call.getName());
                symbol.put("kind", kind);
                symbol.put("span", span(element.getCtx(), formatName, exactLineMapping));
                symbols.add(symbol);
            }
        }
        resolution.put("status", !analysisCompleted || unresolved > 0 ? "ERROR" : "UNKNOWN");
        resolution.put("asgAnalysisCompleted", analysisCompleted);
        resolution.put("resolvedReferences", resolved);
        resolution.put("unresolvedReferences", unresolved);
        resolution.put("asgElements", program.registry.elements.size());
        resolution.put("callTypes", callTypes);
        resolution.put("countsComplete", analysisCompleted);
        structure.put("references", symbols);
        structure.put("referencesTruncated", resolved + unresolved > symbols.size());
        return result;
    }

    private static String adaptFreeSource(String source) {
        // ProLeap does not expose a FREE enum. TANDEM consumes one indicator column;
        // an inserted blank keeps all original FREE characters in its content area.
        String[] lines = source.split("\\R", -1);
        StringBuilder adapted = new StringBuilder();
        for (int i = 0; i < lines.length; i++) {
            if (i > 0) adapted.append('\n');
            adapted.append(' ');
            if (!FREE_DIRECTIVE.matcher(lines[i]).matches()) adapted.append(lines[i]);
        }
        return adapted.toString();
    }

    private static boolean mappingIsSafe(String source, String processed, String format) {
        String[] originalLines = source.split("\\R", -1);
        String[] processedLines = processed.split("\\R", -1);
        // Scanner drops a final empty line; neither source's substantive lines move.
        int originalCount = originalLines.length;
        int processedCount = processedLines.length;
        while (originalCount > 0 && originalLines[originalCount - 1].isBlank()) originalCount--;
        while (processedCount > 0 && processedLines[processedCount - 1].isBlank()) processedCount--;
        if (originalCount != processedCount) return false;
        for (int i = 0; i < processedCount; i++) {
            String original = originalLines[i];
            String processedLine = processedLines[i];
            if (format.equals("FREE") && FREE_DIRECTIVE.matcher(original).matches() && processedLine.isBlank()) continue;
            String expected = format.equals("FREE") ? " " + original : original;
            // Compare content after whitespace; a replacement, continuation or embedded
            // preprocessor rewrite invalidates original-coordinate claims conservatively.
            if (!expected.stripTrailing().equals(processedLine.stripTrailing())) {
                int prefix = format.equals("FREE") ? 1 : format.equals("TANDEM") ? 1 : 7;
                if (expected.length() < prefix || processedLine.length() < prefix
                        || !expected.substring(prefix).stripTrailing().equals(processedLine.substring(prefix).stripTrailing())) return false;
            }
        }
        return true;
    }

    private static int inspectTree(ParseTree tree, List<Map<String, Object>> nodes, Map<String, Integer> counts,
                                   String format, boolean mapped) {
        Deque<ParseTree> stack = new ArrayDeque<>();
        stack.push(tree);
        int total = 0;
        while (!stack.isEmpty()) {
            ParseTree node = stack.pop();
            if (node instanceof ParserRuleContext context) {
                total++;
                String rule = CobolParser.ruleNames[context.getRuleIndex()];
                counts.merge(rule, 1, Integer::sum);
                if (nodes.size() < NODE_LIMIT) {
                    Map<String, Object> record = new LinkedHashMap<>();
                    record.put("kind", rule);
                    record.put("span", span(context, format, mapped));
                    nodes.add(record);
                }
            }
            for (int i = node.getChildCount() - 1; i >= 0; i--) stack.push(node.getChild(i));
        }
        return total;
    }

    private static Map<String, Object> span(ParserRuleContext context, String format, boolean mapped) {
        Map<String, Object> span = new LinkedHashMap<>();
        Token start = context == null ? null : context.getStart();
        Token stop = context == null ? null : context.getStop();
        int shift = mapped && format.equals("FREE") ? 1 : 0;
        span.put("coordinateSpace", mapped ? "ORIGINAL" : "PREPROCESSED");
        span.put("startLine", start == null ? null : start.getLine());
        span.put("startColumn", start == null ? null : Math.max(1, start.getCharPositionInLine() + 1 - shift));
        span.put("endLine", stop == null ? null : stop.getLine());
        span.put("endColumn", stop == null ? null : Math.max(1, stop.getCharPositionInLine() + 1 - shift
                + (stop.getType() == Token.EOF || stop.getText() == null ? 0 : stop.getText().length())));
        return span;
    }

    private static Map<String, Object> diagnostic(String code, String message, Integer line, Integer column, String severity) {
        Map<String, Object> diagnostic = new LinkedHashMap<>();
        diagnostic.put("code", code);
        diagnostic.put("message", message);
        diagnostic.put("line", line);
        diagnostic.put("column", column);
        diagnostic.put("severity", severity);
        return diagnostic;
    }

    private static String safeMessage(Throwable error) {
        String message = error.getMessage();
        if (message == null || message.isBlank()) message = error.getClass().getSimpleName();
        return message.length() > 1500 ? message.substring(0, 1500) : message;
    }

    private static Integer[] errorPosition(String message) {
        Matcher match = LINE_NUMBER.matcher(message);
        if (!match.find()) return new Integer[]{null, null};
        return new Integer[]{Integer.valueOf(match.group(1)), match.group(2) == null ? null : Integer.valueOf(match.group(2)) + 1};
    }

    private static final class CollectingErrors extends BaseErrorListener {
        private final List<Map<String, Object>> diagnostics;
        private final String format;
        private final boolean mapped;
        CollectingErrors(List<Map<String, Object>> diagnostics, String format, boolean mapped) {
            this.diagnostics = diagnostics;
            this.format = format;
            this.mapped = mapped;
        }
        @Override public void syntaxError(Recognizer<?, ?> recognizer, Object offendingSymbol, int line,
                                          int charPositionInLine, String message, RecognitionException exception) {
            if (diagnostics.size() >= DIAGNOSTIC_LIMIT) return;
            int shift = mapped && format.equals("FREE") ? 1 : 0;
            Map<String, Object> entry = diagnostic("ANTLR_SYNTAX_ERROR", message, line,
                    Math.max(1, charPositionInLine + 1 - shift), "ERROR");
            entry.put("coordinateSpace", mapped ? "ORIGINAL" : "PREPROCESSED");
            diagnostics.add(entry);
        }
    }

    private static final class TrackingRegistry extends ASGElementRegistryImpl {
        final List<ASGElement> elements = new ArrayList<>();
        final Set<ASGElement> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        @Override public void addASGElement(ASGElement element) {
            super.addASGElement(element);
            if (seen.add(element)) elements.add(element);
        }
    }

    private static final class TrackingProgram extends ProgramImpl {
        final TrackingRegistry registry = new TrackingRegistry();
        @Override public ASGElementRegistry getASGElementRegistry() { return registry; }
    }

    private static final class ExposedRunner extends CobolParserRunnerImpl {
        void analyzeExisting(Program program) { analyze(program); }
    }
}
