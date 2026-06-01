package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import org.springframework.http.HttpStatus;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.annotation.Tool;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CandidateSearchToolTest {

    @Mock
    private BoondManagerCandidateService candidateService;

    @Test
    void givenQueryOnly_whenSearchCandidates_thenDelegatesWithKeywordRequest() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
                "java",
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEqualTo("java");
        assertThat(requestCaptor.getValue().candidateStates()).isNull();
        assertThat(requestCaptor.getValue().maxResults()).isNull();
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenFilters_whenSearchCandidates_thenDelegatesWithAllFilters() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
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

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue())
                .usingRecursiveComparison()
                .isEqualTo(TestFixtures.searchRequest());
    }

    @Test
    void givenEmptyQuery_whenSearchCandidates_thenDelegatesAccordingToOptionalDtoRules() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
                "",
                null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null,
                1,
                25,
                null, null, null
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEmpty();
        assertThat(requestCaptor.getValue().page()).isEqualTo(1);
        assertThat(requestCaptor.getValue().maxResults()).isEqualTo(25);
    }

    @Test
    void givenBackendException_whenSearchCandidates_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates", new RuntimeException());
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenThrow(exception);

        assertThatThrownBy(() -> tool().searchCandidates(
                "java",
                null, null, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, null, null, null,
                null, null,
                1,
                25,
                null, null, null
        )).isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = CandidateSearchTool.class.getMethod(
                "searchCandidates",
                String.class,        // keywords
                String.class,        // keywordsType
                List.class,          // candidateStates
                List.class,          // candidateTypes
                List.class,          // availabilityTypes
                List.class,          // contractTypes
                List.class,          // experiences
                List.class,          // expertiseAreas
                List.class,          // activityAreas
                String.class,        // mobilityAreas
                List.class,          // languages
                List.class,          // tools
                List.class,          // evaluations
                List.class,          // sources
                List.class,          // shields
                String.class,        // location
                String.class,        // coordinates
                Integer.class,       // geoDistance
                String.class,        // period
                String.class,        // startDate
                String.class,        // endDate
                String.class,        // periodDynamic
                Integer.class,       // page
                Integer.class,       // maxResults
                List.class,          // sort
                String.class,        // order
                List.class           // columns
        ).getAnnotation(Tool.class);

        assertThat(annotation.name()).isEqualTo("searchCandidates");
    }

    @Test
    void givenToolClass_whenInspected_thenDoesNotDependOnBoondManagerClientDirectly() {
        assertThat(Arrays.stream(CandidateSearchTool.class.getDeclaredFields()).map(Field::getType))
                .contains(BoondManagerCandidateService.class)
                .doesNotContain(BoondManagerClient.class);
    }

    private CandidateSearchTool tool() {
        return new CandidateSearchTool(candidateService);
    }
}
