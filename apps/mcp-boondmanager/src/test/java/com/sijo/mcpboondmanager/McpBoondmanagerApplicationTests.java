package com.sijo.mcpboondmanager;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = {
		"boondmanager.base-url=http://localhost:9999",
		"boondmanager.jwt-client=test-jwt",
		"boondmanager.timeout=5s"
})
class McpBoondmanagerApplicationTests {

	@Test
	void contextLoads() {
	}

}
