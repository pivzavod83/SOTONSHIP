package org.omul.parser;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Offline bounded JSON-lines driver. Never generates or executes submitted code. */
public final class ParserMain {
    private static final ObjectMapper JSON = new ObjectMapper();
    public static void main(String[] args) throws Exception {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        for (String line; (line = readBoundedLine(input)) != null;) {
            Map<String, Object> result;
            try {
                JsonNode request = JSON.readTree(line);
                if (!request.path("source").isTextual()) throw new IllegalArgumentException("source must be text");
                String source = request.path("source").asText();
                if (source.length() > 200_000) throw new IllegalArgumentException("Source character budget exceeded");
                String format = request.path("sourceFormat").asText("FREE");
                String filename = request.path("filename").asText("Submitted.java");
                result = switch (request.path("language").asText()) {
                    case "Java" -> JavaFrontend.inspect(source, format, filename);
                    case "COBOL" -> CobolFrontend.inspect(source, format, filename);
                    default -> throw new IllegalArgumentException("language must be Java or COBOL");
                };
            } catch (Exception | LinkageError ex) {
                result = Map.of("error", ex.getClass().getSimpleName(), "message", String.valueOf(ex.getMessage()),
                                "sourcesExecuted", false);
            }
            System.out.println(JSON.writeValueAsString(result));
            System.out.flush();
        }
    }
    private static String readBoundedLine(BufferedReader input) throws Exception {
        StringBuilder line = new StringBuilder();
        for (int c; (c = input.read()) != -1;) {
            if (c == '\n') return line.toString();
            if (line.length() >= 1_500_000) throw new IllegalArgumentException("JSON request budget exceeded");
            line.append((char)c);
        }
        return line.isEmpty() ? null : line.toString();
    }
}
