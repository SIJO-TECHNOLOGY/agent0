package com.sijo.mcpboondmanager.support;

import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
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
                "resumeTd",
                List.of(2, 5),
                null,
                List.of(9),
                List.of(1),
                List.of(3),
                List.of("backend", "microservices"),
                List.of("profilsdeveloppeur"),
                "idf",
                List.of("anglais|courant"),
                List.of("JAVA"),
                List.of("4"),
                List.of("4"),
                List.of("complete"),
                "Paris",
                null,
                50,
                "updated",
                "2026-01-01",
                "2026-06-01",
                null,
                1,
                25,
                List.of("updateDate"),
                "desc",
                List.of("name", "title", "state", "availability", "expertiseAreas", "experience")
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
                "9",
                2,
                List.of("idf"),
                "Paris",
                "FR",
                "Senior Java Engineer",
                3,
                "Java, Spring, React",
                List.of("Engineering school"),
                List.of("backend"),
                List.of("finance"),
                List.of(new TechnicalDocumentDto.ToolProficiency("IntelliJ", 5)),
                List.of(new TechnicalDocumentDto.LanguageProficiency("fr", "native"))
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
                null,
                1,
                "1990-01-01",
                "1 rue de test",
                "75001",
                "Paris",
                "FR",
                null,
                "STAGIAIRE",
                "A. L.",
                1,
                2,
                "9",
                List.of("idf"),
                1,
                "LinkedIn",
                "4",
                "Strong backend profile",
                "2025-01-01",
                "2026-02-01",
                "manual"
        );
    }

    public static TechnicalDocumentDto technicalDocument() {
        return new TechnicalDocumentDto(
                42,
                "101",
                "Senior Java Engineer",
                "Detailed technical profile",
                "Backend engineer",
                3,
                "bac5",
                List.of("Engineering school"),
                "Java, Spring, PostgreSQL",
                List.of("backend"),
                List.of("finance"),
                List.of(new TechnicalDocumentDto.ToolProficiency("IntelliJ", 5)),
                List.of(new TechnicalDocumentDto.LanguageProficiency("en", "fluent")),
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
        DictionaryOptionEntryDto activity = new DictionaryOptionEntryDto(
                List.of(new DictionaryOptionEntryDto.OptionId("finance", "Finance")),
                "Sectors"
        );

        return new DictionaryResponseDto(new DictionarySettingDto(
                new DictionarySettingDto.State(List.of(activeState)),
                new DictionarySettingDto.TypeOf(List.of(contract)),
                List.of(availability),
                List.of(mobility),
                List.of(new DictionaryEntryDto("3", "Senior")),
                List.of(new DictionaryEntryDto("bac5", "Bac+5")),
                List.of(new DictionaryEntryDto("backend", "Backend")),
                List.of(activity),
                List.of(new DictionaryEntryDto("java", "Java")),
                List.of(new DictionaryEntryDto("fr", "French")),
                List.of(new DictionaryEntryDto("5", "Native")),
                List.of(new DictionaryEntryDto("4", "Excellent")),
                List.of(new DictionaryEntryDto("1", "LinkedIn"))
        ));
    }
}
