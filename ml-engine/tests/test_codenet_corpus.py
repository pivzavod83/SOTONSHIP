from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from ml_engine.codenet_corpus import CorpusError, Limits, prepare_cobol, prepare_java, report_summary

FIELDS = ['submission_id', 'problem_id', 'user_id', 'date', 'language', 'original_language',
          'filename_ext', 'status', 'cpu_time', 'memory', 'code_size', 'accuracy']


def metadata(problem: str, records: list[tuple[str, str, str, str, str]]) -> bytes:
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader()
    for identifier, language, status, user, date in records:
        row = {field: '' for field in FIELDS}
        row.update(submission_id=identifier, problem_id=problem, user_id=user, date=date,
                   language=language, original_language=language, status=status,
                   filename_ext='cob' if language == 'COBOL' else 'java')
        writer.writerow(row)
    return output.getvalue().encode()


def archive(path: Path, members: list[tuple[str, bytes | str | None]]) -> Path:
    with tarfile.open(path, 'w:gz') as handle:
        for name, value in members:
            info = tarfile.TarInfo(name)
            if value is None:
                info.type = tarfile.SYMTYPE
                info.linkname = '/tmp/unsafe'
                handle.addfile(info)
            else:
                raw = value.encode() if isinstance(value, str) else value
                info.size = len(raw)
                handle.addfile(info, io.BytesIO(raw))
    return path


def fixture_archive(tmp_path: Path) -> Path:
    return archive(tmp_path / 'archive.tar.gz', [
        ('Project_CodeNet/problem_descriptions/p00001.html', '<p>shared I/O</p>'),
        ('Project_CodeNet/problem_descriptions/p09999.html', '<p>other task</p>'),
        ('Project_CodeNet/LICENSE', 'CDLA-Permissive-2.0'),
        ('Project_CodeNet/metadata/p00001.csv', metadata('p00001', [
            ('s1', 'COBOL', 'Accepted', 'u1', '1'),
            ('s2', 'Java', 'Wrong Answer', 'u2', '2'),
            ('s3', 'Java', 'Accepted', 'u2', '3'),
            ('s4', 'Java', 'Accepted', 'u2', '4'),
            ('s5', 'Java', 'Compile Error', 'u3', '5'),
            ('s6', 'Python', 'Accepted', 'u1', '6'),
        ])),
        ('Project_CodeNet/metadata/p09999.csv', metadata('p09999', [('other', 'Java', 'Accepted', 'u', '1')])),
        # Deliberately put Java before COBOL. Source/member ordering is irrelevant.
        ('Project_CodeNet/data/p00001/Java/s2.java', 'wrong\r\n'),
        ('Project_CodeNet/data/p00001/Java/s3.java', 'right\n'),
        ('Project_CodeNet/data/p00001/Java/s4.java', 'right\n'),
        ('Project_CodeNet/data/p00001/Java/s5.java', 'broken\n'),
        ('Project_CodeNet/data/p09999/Java/other.java', 'unrelated'),
        ('Project_CodeNet/data/p00001/COBOL/s1.cob', '       IDENTIFICATION DIVISION.\r\n'),
        ('Project_CodeNet/derived/input-output/p00001/input.txt', '2\n'),
        ('Project_CodeNet/derived/input-output/p09999/input.txt', 'unrelated'),
        ('Project_CodeNet/derived/duplicate_clusters/Java.csv', 'cluster metadata'),
        ('Project_CodeNet/derived/benchmarks/huge.bin', 'do not extract'),
    ])


def test_two_pass_extraction_metadata_and_unlabelled_history(tmp_path: Path):
    source = fixture_archive(tmp_path)
    output = tmp_path / 'corpus'
    first = prepare_cobol(source, output, collection_date='2026-10-20')
    assert first['problemIds'] == ['p00001']
    assert len(first['sourceFiles']) == 1
    assert first['derivedLayoutCensus']['input-output']['regularFiles'] == 2
    assert first['derivedLayoutCensus']['benchmarks']['regularFiles'] == 1
    assert first['derivedLayoutCensus']['duplicate_clusters']['exampleMembers'] == ['Project_CodeNet/derived/duplicate_clusters/Java.csv']
    assert not (output / 'data/p00001/Java').exists()
    assert (output / 'problem_descriptions/p09999.html').exists()
    filtered = (output / 'metadata/p00001.csv').read_text()
    assert 'Python' not in filtered
    assert not (output / 'metadata/p09999.csv').exists()
    result = prepare_java(source, output)
    assert result['sourceFileCount'] == {'COBOL': 1, 'Java': 4}
    assert result['crossLanguageCandidateFamilyCount'] == 1
    assert result['javaWrongAnswerToAcceptedHistoryCount'] == 1
    assert result['metadataStatusDistribution']['Java']['Compile Error'] == 1
    assert result['sourcesExecuted'] is False
    assert result['trainingEligible'] is False
    assert result['defectLabelsAssigned'] == 0
    assert not result['atLeastTenCandidateFamilies']
    assert not (output / 'data/p09999').exists()
    assert not (output / 'derived/benchmarks').exists()
    assert (output / 'derived/input-output/p00001/input.txt').exists()
    assert not (output / 'derived/input-output/p09999').exists()
    histories = [json.loads(line) for line in (output / 'candidate-histories.jsonl').read_text().splitlines()]
    assert len(histories) == 1
    assert histories[0]['javaBefore']['submissionId'] == 's2'
    assert histories[0]['javaAfter']['submissionId'] == 's3'
    assert histories[0]['semanticLabel'] is None
    assert histories[0]['trainingEligible'] is False
    assert 'not a demonstrated' in histories[0]['relationship']
    record = next(row for row in result['sourceFiles'] if row['submissionId'] == 's2')
    assert record['sha256'] == hashlib.sha256(b'wrong\r\n').hexdigest()
    assert (output / record['path']).read_bytes() == b'wrong\r\n'
    summary = report_summary(result)
    assert 'sourceFiles' not in summary
    assert 'userId' not in json.dumps(summary)
    assert len(summary['implementation']['sha256']) == 64


@pytest.mark.parametrize('name', ['../escape', '/absolute/file', 'Project_CodeNet/../escape', 'bad\\path'])
def test_unsafe_paths_rejected(tmp_path: Path, name: str):
    source = archive(tmp_path / 'unsafe.tar.gz', [(name, 'anything')])
    with pytest.raises(CorpusError, match='Unsafe archive member'):
        prepare_cobol(source, tmp_path / 'out', collection_date='2026-10-20')
    assert not (tmp_path / 'escape').exists()


def test_symlinks_and_selected_budgets_rejected(tmp_path: Path):
    source = archive(tmp_path / 'symlink.tar.gz', [('Project_CodeNet/data/p00001/COBOL/a.cob', None)])
    with pytest.raises(CorpusError, match='member type'):
        prepare_cobol(source, tmp_path / 'links', collection_date='2026-10-20')
    source = archive(tmp_path / 'big.tar.gz', [('Project_CodeNet/data/p00001/COBOL/a.cob', '12345')])
    with pytest.raises(CorpusError, match='file budget'):
        prepare_cobol(source, tmp_path / 'large', collection_date='2026-10-20', limits=Limits(max_source_bytes=4))
    with pytest.raises(CorpusError, match='decompression budget'):
        prepare_cobol(source, tmp_path / 'decompress', collection_date='2026-10-20', limits=Limits(max_archive_uncompressed_bytes=4))


def test_expected_hash_stage_hash_and_no_overwrite(tmp_path: Path):
    source = fixture_archive(tmp_path)
    output = tmp_path / 'out'
    with pytest.raises(CorpusError, match='SHA-256 mismatch'):
        prepare_cobol(source, output, collection_date='2026-10-20', expected_sha256='0' * 64)
    assert not output.exists()
    prepare_cobol(source, output, collection_date='2026-10-20')
    with pytest.raises(CorpusError, match='must not already exist'):
        prepare_cobol(source, output, collection_date='2026-10-20')
    prepare_java(source, output)
    with pytest.raises(CorpusError, match='cannot be overwritten'):
        prepare_java(source, output)


def test_metadata_tampering_and_source_tampering_detected(tmp_path: Path):
    source = fixture_archive(tmp_path)
    output = tmp_path / 'out'
    prepare_cobol(source, output, collection_date='2026-10-20')
    (output / 'metadata/p00001.csv').write_text('changed')
    with pytest.raises(CorpusError, match='metadata modified'):
        prepare_java(source, output)
    output2 = tmp_path / 'out2'
    prepare_cobol(source, output2, collection_date='2026-10-20')
    (output2 / 'data/p00001/COBOL/s1.cob').write_bytes(b'changed')
    with pytest.raises(CorpusError, match='source modified'):
        prepare_java(source, output2)


def test_chronology_same_timestamp_unknown_dates_and_different_users_are_not_repairs(tmp_path: Path):
    rows = [('c', 'COBOL', 'Accepted', 'uc', '1'),
            ('a', 'Java', 'Wrong Answer', 'u1', '2'),
            ('b', 'Java', 'Accepted', 'u2', '3'),
            ('d', 'Java', 'Accepted', 'u1', '2'),
            ('e', 'Java', 'Accepted', 'u1', 'unknown')]
    members = [('Project_CodeNet/metadata/p00001.csv', metadata('p00001', rows))]
    members += [(f'Project_CodeNet/data/p00001/{lang}/{identifier}.{"cob" if lang == "COBOL" else "java"}', 'code') for identifier, lang, *_ in rows]
    source = archive(tmp_path / 'dates.tar.gz', members)
    output = tmp_path / 'out'
    prepare_cobol(source, output, collection_date='2026-10-20')
    result = prepare_java(source, output)
    assert result['javaWrongAnswerToAcceptedHistoryCount'] == 0
    assert result['invalidJavaSubmissionDateCount'] == 1


def test_non_utf8_sources_are_preserved_but_not_accepted_anchors(tmp_path: Path):
    source = archive(tmp_path / 'encoding.tar.gz', [
        ('Project_CodeNet/metadata/p00001.csv', metadata('p00001', [('c', 'COBOL', 'Accepted', 'u', '1'), ('j', 'Java', 'Accepted', 'v', '2')])),
        ('Project_CodeNet/data/p00001/COBOL/c.cob', b'\xff'),
        ('Project_CodeNet/data/p00001/Java/j.java', 'code'),
    ])
    output = tmp_path / 'out'
    prepare_cobol(source, output, collection_date='2026-10-20')
    result = prepare_java(source, output)
    assert (output / 'data/p00001/COBOL/c.cob').read_bytes() == b'\xff'
    assert result['crossLanguageCandidateFamilyCount'] == 0
    assert result['sourceFiles'][0]['encoding'] == 'NON_UTF8_REQUIRES_REVIEW'


def test_duplicate_selected_member_and_bad_metadata_are_rejected(tmp_path: Path):
    source = archive(tmp_path / 'dup.tar.gz', [
        ('Project_CodeNet/data/p00001/COBOL/c.cob', 'one'),
        ('Project_CodeNet/data/p00001/COBOL/c.cob', 'two'),
    ])
    with pytest.raises(CorpusError, match='Duplicate'):
        prepare_cobol(source, tmp_path / 'out', collection_date='2026-10-20')
    source = archive(tmp_path / 'badmeta.tar.gz', [('Project_CodeNet/metadata/p00001.csv', 'no,columns\n1,2\n')])
    with pytest.raises(CorpusError, match='metadata columns'):
        prepare_cobol(source, tmp_path / 'out2', collection_date='2026-10-20')


def test_derived_layout_census_has_bounded_examples_without_extracting_unknown_data(tmp_path: Path):
    members = [(f'Project_CodeNet/derived/unknown_layout/folder{i}/file.dat', 'unselected') for i in range(20)]
    source = archive(tmp_path / 'derived.tar.gz', members)
    output = tmp_path / 'out'
    first = prepare_cobol(source, output, collection_date='2026-10-20')
    census = first['derivedLayoutCensus']['unknown_layout']
    assert census['regularFiles'] == 20
    assert census['uncompressedBytes'] == 20 * len('unselected')
    assert len(census['exampleMembers']) == 8
    assert not (output / 'derived').exists()
