package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
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
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BoondDictionaryToolTest {

    @Mock
    private BoondManagerCandidateService candidateService;

    @Test
    void givenDictionaryRequest_whenGetDictionary_thenReturnsServiceResponse() {
        DictionaryResponseDto expected = TestFixtures.dictionary();
        when(candidateService.getDictionary()).thenReturn(expected);

        DictionaryResponseDto response = tool().getDictionary();

        assertThat(response).isSameAs(expected);
        verify(candidateService).getDictionary();
        verifyNoMoreInteractions(candidateService);
    }

    @Test
    void givenBackendException_whenGetDictionary_thenPropagatesProjectException() {
        BoondApiException exception = new BoondApiException(
                "backend failed", HttpStatus.INTERNAL_SERVER_ERROR, "/application/dictionary", new RuntimeException());
        when(candidateService.getDictionary()).thenThrow(exception);

        assertThatThrownBy(() -> tool().getDictionary())
                .isSameAs(exception);
    }

    @Test
    void givenToolClass_whenInspected_thenToolNameRemainsUnchanged() throws NoSuchMethodException {
        Tool annotation = BoondDictionaryTool.class
                .getMethod("getDictionary")
                .getAnnotation(Tool.class);

        assertThat(annotation.name()).isEqualTo("getDictionary");
    }

    @Test
    void givenToolClass_whenInspected_thenDoesNotDependOnBoondManagerClientDirectly() {
        assertThat(Arrays.stream(BoondDictionaryTool.class.getDeclaredFields()).map(Field::getType))
                .contains(BoondManagerCandidateService.class)
                .doesNotContain(BoondManagerClient.class);
    }

    private BoondDictionaryTool tool() {
        return new BoondDictionaryTool(candidateService);
    }
}
