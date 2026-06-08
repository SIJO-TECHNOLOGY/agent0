package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import org.springframework.http.HttpStatus;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import com.sijo.mcpboondmanager.support.TestFixtures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.annotation.Tool;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.RecordComponent;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CandidateTechnicalDocToolTest {

    @Mock
    private BoondManagerCandidateService candidateService;

    @Test
    void givenCandidateId_whenGetTechnicalDocument_thenReturnsServiceResponse() {
        TechnicalDocumentDto expected = TestFixtures.technicalDocument();
        when(candidateService.getCandidateTechnicalDocument(42)).thenReturn(expected);

        TechnicalDocumentDto response = tool().getCandidateTechnicalDocument(42, true);

        assertThat(response).isSameAs(expected);
        verify(candidateService).getCandidateTechnicalDocument(42);
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenNoIncludeRawSkillsText_whenGetTechnicalDocument_thenKeepsSkillsByDefault() {
        TechnicalDocumentDto expected = TestFixtures.technicalDocument();
        when(candidateService.getCandidateTechnicalDocument(42)).thenReturn(expected);

        TechnicalDocumentDto response = tool().getCandidateTechnicalDocument(42, null);

        // includeRawSkillsText defaults to true — same instance returned, skills text intact.
        assertThat(response).isSameAs(expected);
        assertThat(response.skills()).isNotBlank();
    }

    @Test
    void givenIncludeRawSkillsTextFalse_whenGetTechnicalDocument_thenStripsRawSkillsOnly() {
        TechnicalDocumentDto backend = TestFixtures.technicalDocument();
        when(candidateService.getCandidateTechnicalDocument(42)).thenReturn(backend);

        TechnicalDocumentDto response = tool().getCandidateTechnicalDocument(42, false);

        assertThat(response.skills()).isNull();
        // Structured fields and the rest of the document are preserved.
        assertThat(response.id()).isEqualTo(backend.id());
        assertThat(response.tdId()).isEqualTo(backend.tdId());
        assertThat(response.title()).isEqualTo(backend.title());
        assertThat(response.summary()).isEqualTo(backend.summary());
        assertThat(response.diplomas()).isEqualTo(backend.diplomas());
        assertThat(response.expertiseAreas()).isEqualTo(backend.expertiseAreas());
        assertThat(response.tools()).isEqualTo(backend.tools());
        assertThat(response.languages()).isEqualTo(backend.languages());
        assertThat(response.references()).isEqualTo(backend.references());
    }

    @Test
    void givenNullCandidateId_whenGetTechnicalDocument_thenDelegatesCurrentServiceBehavior() {
        TechnicalDocumentDto expected = TestFixtures.technicalDocument();
        when(candidateService.getCandidateTechnicalDocument(null)).thenReturn(expected);

        TechnicalDocumentDto response = tool().getCandidateTechnicalDocument(null, true);

        assertThat(response).isSameAs(expected);
        verify(candidateService).getCandidateTechnicalDocument(null);
    }

    @Test
    void givenBackendException_whenGetTechnicalDocument_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR,
                "/candidates/42/technical-data", new RuntimeException());
        when(candidateService.getCandidateTechnicalDocument(42)).thenThrow(exception);

        assertThatThrownBy(() -> tool().getCandidateTechnicalDocument(42, true))
                .isSameAs(exception);
    }

    @Test
    void givenNotFoundException_whenGetTechnicalDocument_thenPropagatesException() {
        RuntimeException exception = new RuntimeException("Technical document not found for candidate: 42");
        when(candidateService.getCandidateTechnicalDocument(42)).thenThrow(exception);

        assertThatThrownBy(() -> tool().getCandidateTechnicalDocument(42, true))
                .isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = CandidateTechnicalDocTool.class
                .getMethod("getCandidateTechnicalDocument", Integer.class, Boolean.class)
                .getAnnotation(Tool.class);

        assertThat(annotation.name()).isEqualTo("getCandidateTechnicalDocument");
    }

    @Test
    void givenToolDescription_whenInspected_thenDocumentsEveryReturnedField() {
        Method method = Arrays.stream(CandidateTechnicalDocTool.class.getMethods())
                .filter(m -> m.getName().equals("getCandidateTechnicalDocument"))
                .findFirst()
                .orElseThrow();
        String description = method.getAnnotation(Tool.class).description();

        for (RecordComponent component : TechnicalDocumentDto.class.getRecordComponents()) {
            assertThat(description)
                    .as("@Tool description should document the returned field '%s'", component.getName())
                    .contains(component.getName());
        }
        assertThat(description).contains("includeRawSkillsText");
    }

    @Test
    void givenToolClass_whenInspected_thenDoesNotDependOnBoondManagerClientDirectly() {
        assertThat(Arrays.stream(CandidateTechnicalDocTool.class.getDeclaredFields()).map(Field::getType))
                .contains(BoondManagerCandidateService.class)
                .doesNotContain(BoondManagerClient.class);
    }

    private CandidateTechnicalDocTool tool() {
        return new CandidateTechnicalDocTool(candidateService);
    }
}
