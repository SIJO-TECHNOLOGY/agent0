package com.sijo.mcpboondmanager.config;

import com.sijo.mcpboondmanager.tools.BoondDictionaryTool;
import com.sijo.mcpboondmanager.tools.CandidateDetailTool;
import com.sijo.mcpboondmanager.tools.CandidateSearchTool;
import com.sijo.mcpboondmanager.tools.CandidateTechnicalDocTool;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class McpServerConfiguration {

    @Bean
    public ToolCallbackProvider boondToolCallbackProvider(
            BoondDictionaryTool dictionaryTool,
            CandidateSearchTool searchTool,
            CandidateDetailTool detailTool,
            CandidateTechnicalDocTool technicalDocTool
    ) {
        return MethodToolCallbackProvider.builder()
                .toolObjects(dictionaryTool, searchTool, detailTool, technicalDocTool)
                .build();
    }
}