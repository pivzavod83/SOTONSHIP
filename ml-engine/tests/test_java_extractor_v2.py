"""Source-only regression checks for typed extraction; no submitted Java runs."""
import json
from pathlib import Path
import unittest

from ml_engine.java_extractor_v2 import extract_java


def program(body, return_type="void", parameters="String[] args", name="main"):
    return f"import java.math.BigDecimal; import java.math.BigInteger; import java.math.RoundingMode; import java.util.Scanner; public class Program {{ public static {return_type} {name}({parameters}) {{ {body} }} }}"


def operations(ir, op):
    return [node for node in ir.nodes if node.op == op]


def lookup(ir, node_id):
    return next(node for node in ir.nodes if node.id == node_id)


class JavaExtractorV2Tests(unittest.TestCase):
    def test_multiline_decimal_chain_preserves_source_lines_and_call_semantics(self):
        source = '\r\n'.join([
            'import java.math.BigDecimal;', 'import java.math.RoundingMode;',
            'public class Program {', '  public static BigDecimal calculate(BigDecimal base, BigDecimal rate) {',
            '    BigDecimal result = base', '        .multiply(rate)', '        .setScale(',
            '           2, RoundingMode.HALF_UP);', '    return result;', '  }', '}',
        ])
        ir = extract_java(source)
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        quantize = operations(ir, 'quantize')[0]
        self.assertEqual((quantize.span.start_line, quantize.span.end_line), (5, 8))
        self.assertEqual(quantize.attrs['scale'], 2)
        self.assertEqual(quantize.attrs['rounding_mode'], 'HALF_UP')
        self.assertIn('\r\n', quantize.source)
        self.assertEqual(operations(ir, 'return')[0].attrs['method'], 'calculate')
        self.assertTrue(operations(ir, 'return')[0].inputs)

    def test_decimal_string_constructor_is_distinct_from_binary_double_constructor(self):
        string_ir = extract_java(program('BigDecimal x = new BigDecimal("0.1"); System.out.println(x);'))
        double_ir = extract_java(program('BigDecimal x = new BigDecimal(0.1); System.out.println(x);'))
        self.assertEqual(string_ir.status, 'COMPLETE')
        self.assertEqual(double_ir.status, 'COMPLETE')
        self.assertEqual(operations(string_ir, 'convert')[0].attrs['decimal_construction'], 'DECIMAL_STRING')
        self.assertEqual(operations(double_ir, 'convert')[0].attrs['decimal_construction'], 'EXACT_BINARY_FLOAT_VALUE')
        self.assertNotEqual(string_ir.fingerprint(), double_ir.fingerprint())
        self.assertEqual(operations(double_ir, 'literal')[0].attrs['value'], '0.1')

    def test_reassignment_preserves_long_type_and_new_definition_reaches_return(self):
        ir = extract_java(program('long saved = 10L; saved = value; saved += 2L; return saved;', 'long', 'long value', 'calculate'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        saved = next(value for key, value in ir.symbols.items() if 'saved#' in key)
        self.assertEqual(saved['numericType']['bit_width'], 64)
        self.assertEqual(len(saved['versions']), 4)  # declaration plus three stores
        returned = lookup(ir, operations(ir, 'return')[0].inputs[0])
        self.assertEqual(returned.inputs, [saved['latest']])
        self.assertIsNone(saved['constant'])
        self.assertEqual(lookup(ir, saved['latest']).numeric_type.bit_width, 64)

    def test_if_else_creates_join_definition_and_distinguishes_branch_edges(self):
        ir = extract_java(program('long result = 0L; if (input > 0L) { result = input; } else { result = -input; } return result;', 'long', 'long input', 'absolute'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        joins = [node for node in operations(ir, 'merge') if node.attrs.get('symbol', '').split('::')[-1].startswith('result#')]
        self.assertEqual(len(joins), 1)
        self.assertEqual(len(joins[0].inputs), 2)
        returned = lookup(ir, operations(ir, 'return')[0].inputs[0])
        self.assertEqual(returned.inputs, [joins[0].id])
        self.assertTrue(any(edge.kind == 'control' and edge.attrs.get('arm') == 'FALSE' for edge in ir.edges))

    def test_while_has_header_phis_loop_carried_data_and_zero_iteration_path(self):
        ir = extract_java(program('long a = left; long b = right; while (b != 0L) { long remainder = a % b; a = b; b = remainder; } return a;', 'long', 'long left, long right', 'gcd'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        headers = [node for node in operations(ir, 'merge') if node.attrs.get('loop_header')]
        self.assertEqual(len(headers), 2)
        self.assertTrue(all(len(node.inputs) == 2 for node in headers))
        self.assertTrue(any(edge.kind == 'loop' and edge.attrs.get('symbol') for edge in ir.edges))
        self.assertTrue(any(node.attrs.get('control_join') == 'WHILE_EXIT' for node in ir.nodes))
        b_header = next(node for node in headers if '::b#' in node.attrs['symbol'])
        loop = operations(ir, 'loop')[0]
        comparison = lookup(ir, loop.inputs[0]); predicate_read = lookup(ir, comparison.inputs[0])
        self.assertEqual(predicate_read.inputs, [b_header.id])
        self.assertEqual(operations(ir, 'modulo')[0].attrs['remainder_sign'], 'DIVIDEND')

    def test_cast_negative_literal_and_integer_division_are_explicit(self):
        ir = extract_java(program('long value = (long) -9; long quotient = value / 2L; return quotient;', 'long', '', 'calculate'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        self.assertEqual(operations(ir, 'divide')[0].attrs['rounding_mode'], 'TRUNCATE_TOWARD_ZERO')
        cast = next(node for node in operations(ir, 'convert') if node.attrs.get('conversion') == 'EXPLICIT_JAVA_CAST')
        self.assertEqual(cast.numeric_type.bit_width, 64)
        self.assertEqual(lookup(ir, cast.inputs[0]).op, 'negate')

    def test_input_output_and_return_are_observable_not_silently_removed(self):
        ir = extract_java(program('Scanner scanner = new Scanner(System.in); long amount = Long.parseLong(scanner.nextLine().trim()); System.out.println(amount);'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        business_inputs = [node for node in operations(ir, 'input') if 'input_index' in node.attrs]
        self.assertEqual(len(business_inputs), 1)
        self.assertEqual(len(operations(ir, 'output')), 1)
        self.assertEqual(ir.attrs['inputCount'], 1)
        returned = extract_java(program('if (x > 0) return x; else return -x;', 'int', 'int x', 'absolute'))
        self.assertEqual(returned.status, 'COMPLETE', returned.issues)
        self.assertEqual(len(operations(returned, 'return')), 2)

    def test_unknown_calls_unresolved_symbols_and_for_loops_fail_explicitly(self):
        cases = [
            ('long x = unknown; System.out.println(x);', 'JAVA_UNRESOLVED_SYMBOL'),
            ('long x = Mystery.calculate(1); System.out.println(x);', 'JAVA_UNSUPPORTED_CALL'),
            ('BigDecimal x = new BigDecimal("1").mystery(); System.out.println(x);', 'JAVA_UNSUPPORTED_CALL'),
            ('for (int i = 0; i < 3; i++) { System.out.println(i); }', 'JAVA_UNSUPPORTED_CONTROL'),
            ('Widget x = new Widget();', 'JAVA_UNRESOLVED_SYMBOL'),
            ('long[] values = new long[3];', 'JAVA_UNSUPPORTED_ARRAY'),
        ]
        for body, code in cases:
            with self.subTest(body=body):
                ir = extract_java(program(body))
                self.assertNotEqual(ir.status, 'COMPLETE')
                self.assertIn(code, {issue.code for issue in ir.issues})

    def test_invalid_typed_operands_guards_shadowing_and_missing_imports_are_issues(self):
        for body, code in [
            ('long x = 1L; if (x) { x = 2L; }', 'JAVA_NON_BOOLEAN_CONDITION'),
            ('BigDecimal x = new BigDecimal("1"); BigDecimal y = x.add("2");', 'JAVA_UNSUPPORTED_CALL'),
            ('BigDecimal x = new BigDecimal("1"); BigDecimal y = x + x;', 'JAVA_BINARY_TYPE'),
            ('long x = 1L; boolean y = x && true;', 'JAVA_BINARY_TYPE'),
            ('long x = 1L; if (true) { long x = 2L; }', 'JAVA_DUPLICATE_LOCAL'),
            ('if (true) long x = 2L;', 'JAVA_INVALID_EMBEDDED_DECLARATION'),
        ]:
            with self.subTest(body=body):
                ir = extract_java(program(body))
                self.assertNotEqual(ir.status, 'COMPLETE')
                self.assertIn(code, {issue.code for issue in ir.issues})
        unresolved = extract_java('class Example { static BigDecimal value() { return new BigDecimal("1"); } }')
        self.assertNotEqual(unresolved.status, 'COMPLETE')
        self.assertIn('JAVA_UNRESOLVED_TYPE', {issue.code for issue in unresolved.issues})

    def test_early_return_excludes_terminated_arm_from_later_return(self):
        ir = extract_java(program('if (x > 0L) { return x; } return -x;', 'long', 'long x', 'absolute'))
        self.assertEqual(ir.status, 'COMPLETE', ir.issues)
        returns = operations(ir, 'return'); self.assertEqual(len(returns), 2)
        continuation = next(node for node in operations(ir, 'branch') if node.attrs.get('condition') == 'RETURN_CONTINUATION')
        self.assertEqual(continuation.attrs['required_arm'], 'FALSE')
        self.assertTrue(any(edge.source == continuation.id and edge.target == returns[1].id and edge.kind == 'control' for edge in ir.edges))
        self.assertFalse(any(edge.source == continuation.id and edge.target == returns[0].id and edge.kind == 'control' for edge in ir.edges))
        unreachable = extract_java(program('if (x > 0L) return x; else return -x; return 0L;', 'long', 'long x', 'absolute'))
        self.assertNotEqual(unreachable.status, 'COMPLETE')
        self.assertIn('JAVA_UNREACHABLE_STATEMENT', {issue.code for issue in unreachable.issues})
        for body in ['{ if (x > 0L) return x; } return -x;', 'while (x > 0L) { return x; } return -x;', 'if (x > 0L) { if (x > 1L) return x; } return -x;']:
            complex_return = extract_java(program(body, 'long', 'long x', 'absolute'))
            self.assertNotEqual(complex_return.status, 'COMPLETE')
            self.assertIn('JAVA_UNSUPPORTED_NESTED_EARLY_RETURN', {issue.code for issue in complex_return.issues})

    def test_comments_formatting_crlf_and_renamed_variables_keep_structure(self):
        compact = program('long total = x + 2L; return total;', 'long', 'long x', 'calculate')
        spaced = 'public class Program {\r\n public static long calculate(long argument) {\r\n // } ; fake syntax\r\n long renamed = argument\r\n + 2L; /* { ignored } */ return renamed;\r\n }\r\n}'
        first, second = extract_java(compact), extract_java(spaced)
        self.assertEqual(first.status, 'COMPLETE')
        self.assertEqual(second.status, 'COMPLETE')
        self.assertEqual(first.fingerprint(), second.fingerprint())
        string = extract_java(program('String x = "{ ; } // actual string"; System.out.println(x);'))
        self.assertEqual(string.status, 'COMPLETE', string.issues)

    def test_malformed_or_ambiguous_constructs_do_not_silently_pass(self):
        for body in ['long x = 1L return x;', 'final long x = 1L; x = 2L;', 'long x = 9223372036854775809L;', 'String x = "\\u000a";', 'long value = 2147483648;']:
            with self.subTest(body=body): self.assertNotEqual(extract_java(program(body)).status, 'COMPLETE')
        minimum = extract_java(program('int x = -2147483648; long y = -9223372036854775808L; System.out.println(x);'))
        self.assertEqual(minimum.status, 'COMPLETE', minimum.issues)

    def test_all_forty_frozen_pilot_sources_parse_without_using_labels(self):
        path = Path(__file__).resolve().parents[1] / 'evaluation/synthetic-pilot/pilot-10-r3/dataset.json'
        data = json.loads(path.read_text())
        sources = ['\n'.join(variant['javaLines']) for family in data['families'] for variant in family['variants']]
        self.assertEqual(len(sources), 40)
        for source in sources:
            ir = extract_java(source)
            self.assertEqual(ir.status, 'COMPLETE', [(issue.code, issue.message) for issue in ir.issues])
            self.assertTrue(operations(ir, 'output'))


if __name__ == '__main__': unittest.main()
