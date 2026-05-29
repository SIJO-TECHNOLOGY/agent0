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
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEqualTo("java");
        assertThat(requestCaptor.getValue().state()).isNull();
        assertThat(requestCaptor.getValue().numberPerPage()).isNull();
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenFilters_whenSearchCandidates_thenDelegatesWithAllFilters() {
        CandidateSearchResponseDto expected = TestFixtures.searchResponse();
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenReturn(expected);

        CandidateSearchResponseDto response = tool().searchCandidates(
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
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                1,
                25
        );

        assertThat(response).isSameAs(expected);
        ArgumentCaptor<CandidateSearchRequestDto> requestCaptor =
                ArgumentCaptor.forClass(CandidateSearchRequestDto.class);
        verify(candidateService).searchCandidates(requestCaptor.capture());
        assertThat(requestCaptor.getValue().keywords()).isEmpty();
        assertThat(requestCaptor.getValue().page()).isEqualTo(1);
        assertThat(requestCaptor.getValue().numberPerPage()).isEqualTo(25);
    }

    @Test
    void givenBackendException_whenSearchCandidates_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR, "/candidates", new RuntimeException());
        when(candidateService.searchCandidates(org.mockito.ArgumentMatchers.any(CandidateSearchRequestDto.class)))
                .thenThrow(exception);

        assertThatThrownBy(() -> tool().searchCandidates(
                "java",
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                1,
                25
        )).isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = CandidateSearchTool.class.getMethod(
                "searchCandidates",
                String.class,
                Integer.class,
                Integer.class,
                String.class,
                Integer.class,
                Integer.class,
                String.class,
                String.class,
                String.class,
                String.class,
                Double.class,
                Double.class,
                Double.class,
                Double.class,
                Integer.class,
                Integer.class
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
