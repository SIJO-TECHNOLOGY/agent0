package com.sijo.mcpboondmanager.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.assertj.core.api.Assertions.assertThat;

class ExperienceLabelParserTest {

    @ParameterizedTest(name = "\"{0}\" -> minYears={1}, openEnded={2}")
    @CsvSource({
            "Pas d'expérience, 0, false",
            "1 an,             1, false",
            "2 ans,            2, false",
            "3 ans,            3, false",
            "4 ans,            4, false",
            "5 ans,            5, false",
            "6 ans,            6, false",
            "7 ans,            7, false",
            "8 ans,            8, false",
            "9 ans,            9, false",
            "10 ans,           10, false",
            "> à 10 ans,       10, true",
            "10 ans et plus,   10, true",
            "10+ ans,          10, true"
    })
    void givenDictionaryLabel_whenParsed_thenMinYearsAndOpenEndedMatch(
            String label, int expectedMinYears, boolean expectedOpenEnded) {
        ExperienceLabelParser.ParsedLabel parsed = ExperienceLabelParser.parse(label);

        assertThat(parsed.minYears()).isEqualTo(expectedMinYears);
        assertThat(parsed.openEnded()).isEqualTo(expectedOpenEnded);
    }

    @Test
    void givenNullLabel_whenParsed_thenZeroAndNotOpenEnded() {
        ExperienceLabelParser.ParsedLabel parsed = ExperienceLabelParser.parse(null);

        assertThat(parsed.minYears()).isZero();
        assertThat(parsed.openEnded()).isFalse();
    }

    @Test
    void givenEnglishOpenEndedLabel_whenParsed_thenOpenEndedIsTrue() {
        ExperienceLabelParser.ParsedLabel parsed = ExperienceLabelParser.parse("10 years and more");

        assertThat(parsed.minYears()).isEqualTo(10);
        assertThat(parsed.openEnded()).isTrue();
    }
}
