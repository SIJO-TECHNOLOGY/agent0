package com.sijo.mcpboondmanager.support;

import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentSummaryDto;
import com.sijo.mcpboondmanager.dto.common.PaginationMetaDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryOptionEntryDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionarySettingDto;

import java.util.List;

public final class TestFixtures {

    private TestFixtures() {
    }

    public static CandidateSearchRequestDto searchRequest() {
        return new CandidateSearchRequestDto(
                "java",
                1,
                9,
                "2026-06-01",
                2,
                3,
                "bac5",
                "backend|microservices",
                "finance|industry",
                "idf",
                40_000.0,
                60_000.0,
                500.0,
                700.0,
                1,
                25
        );
    }

    public static CandidateSearchResponseDto searchResponse() {
        return new CandidateSearchResponseDto(
                List.of(candidateSummary()),
                new PaginationMetaDto(1, 1)
        );
    }

    public static CandidateSummaryDto candidateSummary() {
        return new CandidateSummaryDto(
                42,
                "Ada",
                "Lovelace",
                "ada@example.test",
                1,
                9,
                "2026-06-01",
                2,
                "idf",
                "Paris",
                "FR",
                40_000.0,
                60_000.0,
                500.0,
                700.0,
                technicalDocumentSummary()
        );
    }

    public static TechnicalDocumentSummaryDto technicalDocumentSummary() {
        return new TechnicalDocumentSummaryDto(
                "Senior Java Engineer",
                3,
                "bac5",
                "Engineering school",
                "Java, Spring, React",
                "backend",
                "finance",
                "IntelliJ:5",
                "fr:5|en:4"
        );
    }

    public static CandidateDetailDto candidateDetail() {
        return new CandidateDetailDto(
                42,
                "Ada",
                "Lovelace",
                "ada@example.test",
                null,
                null,
                "+33100000000",
                null,
                null,
                1,
                "1990-01-01",
                "FR",
                "1 rue de test",
                "75001",
                "Paris",
                "FR",
                1,
                4,
                9,
                "2026-06-01",
                2,
                "idf",
                55_000.0,
                60_000.0,
                70_000.0,
                600.0,
                650.0,
                750.0,
                1,
                "LinkedIn",
                "Strong backend profile",
                "2025-01-01",
                "2026-01-01",
                "2026-02-01",
                101,
                7,
                8
        );
    }

    public static TechnicalDocumentDto technicalDocument() {
        return new TechnicalDocumentDto(
                101,
                "Senior Java Engineer",
                "Detailed technical profile",
                "Backend engineer",
                3,
                "bac5",
                "Engineering school",
                "Java, Spring, PostgreSQL",
                "backend",
                "finance",
                "IntelliJ:5",
                "fr:5|en:4",
                Boolean.FALSE,
                "2025-01-01",
                "2026-01-01",
                42
        );
    }

    public static DictionaryResponseDto dictionary() {
        DictionaryEntryDto activeState = new DictionaryEntryDto("1", "Active");
        DictionaryEntryDto contract = new DictionaryEntryDto("2", "CDI");
        DictionaryEntryDto availability = new DictionaryEntryDto("9", "Available after date");
        DictionaryOptionEntryDto mobility = new DictionaryOptionEntryDto(
                List.of(new DictionaryOptionEntryDto.OptionId("idf", "Ile-de-France")),
                "Ile-de-France"
        );

        return new DictionaryResponseDto(new DictionarySettingDto(
                new DictionarySettingDto.State(List.of(activeState)),
                new DictionarySettingDto.TypeOf(List.of(contract)),
                List.of(availability),
                List.of(mobility),
                List.of(new DictionaryEntryDto("3", "Senior")),
                List.of(new DictionaryEntryDto("bac5", "Bac+5")),
                List.of(new DictionaryEntryDto("backend", "Backend")),
                List.of(new DictionaryEntryDto("finance", "Finance")),
                List.of(new DictionaryEntryDto("java", "Java")),
                List.of(new DictionaryEntryDto("fr", "French")),
                List.of(new DictionaryEntryDto("5", "Native")),
                List.of(new DictionaryEntryDto("4", "Excellent")),
                List.of(new DictionaryEntryDto("1", "LinkedIn"))
        ));
    }
}
