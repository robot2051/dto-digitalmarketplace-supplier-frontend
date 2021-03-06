# -*- coding: utf-8 -*-
try:
    from StringIO import StringIO
except ImportError:
    from io import BytesIO as StringIO

from dmapiclient import HTTPError
from dmutils.forms import FakeCsrf
import copy
import mock
import pytest
from lxml import html
from freezegun import freeze_time

from nose.tools import assert_equal, assert_true, assert_false, assert_in, assert_not_in
from tests.app.helpers import BaseApplicationTest, empty_g7_draft, csrf_only_request


@pytest.fixture(params=["g-cloud-6", "g-cloud-7"])
def fixture_framework_slug_and_name(request):
    frameworks = {
        'g-cloud-6': ('g-cloud-6', 'G-Cloud 6'),
        'g-cloud-7': ('g-cloud-7', 'G-Cloud 7')
    }

    return frameworks[request.param]


class TestListServices(BaseApplicationTest):
    @mock.patch('app.main.views.services.data_api_client')
    def test_shows_no_services_message(self, data_api_client):
        with self.app.test_client():
            self.login()

            data_api_client.find_services.return_value = {
                "services": []
                }

            res = self.client.get(self.url_for('main.list_services'))
            assert_equal(res.status_code, 200)
            data_api_client.find_services.assert_called_once_with(
                supplier_code=1234)
            assert_in(
                "You don&#39;t have any services on the Digital Marketplace",
                res.get_data(as_text=True)
            )

    @mock.patch('app.main.views.services.data_api_client')
    def test_shows_services_list(self, data_api_client):
        with self.app.test_client():
            self.login()

            data_api_client.find_services.return_value = {
                'services': [{
                    'serviceName': 'Service name 123',
                    'status': 'published',
                    'id': '123',
                    'lotSlug': 'saas',
                    'lotName': 'Software as a Service',
                    'frameworkName': 'G-Cloud 1',
                    'frameworkSlug': 'g-cloud-1'
                }]
            }

            res = self.client.get(self.url_for('main.list_services'))
            assert_equal(res.status_code, 200)
            data_api_client.find_services.assert_called_once_with(
                supplier_code=1234)
            assert_true("Service name 123" in res.get_data(as_text=True))
            assert_true("Software as a Service" in res.get_data(as_text=True))
            assert_true("G-Cloud 1" in res.get_data(as_text=True))

    @mock.patch('app.data_api_client')
    def test_should_not_be_able_to_see_page_if_made_inactive(self, services_data_api_client):
        with self.app.test_client():
            self.login(active=False)

            services_url = self.url_for('main.list_services')
            res = self.client.get(services_url)
            assert_equal(res.status_code, 302)
            assert_equal(res.location, self.get_login_redirect_url(services_url))

    @mock.patch('app.main.views.services.data_api_client')
    def test_shows_service_edit_link_with_id(self, data_api_client):
        with self.app.test_client():
            self.login()

            data_api_client.find_services.return_value = {
                'services': [{
                    'serviceName': 'Service name 123',
                    'status': 'published',
                    'id': '123',
                    'frameworkSlug': 'g-cloud-1'
                }]
            }

            res = self.client.get(self.url_for('main.list_services'))
            assert_equal(res.status_code, 200)
            data_api_client.find_services.assert_called_once_with(
                supplier_code=1234)
            assert_true(
                self.url_for('main.edit_service', service_id=123) in res.get_data(as_text=True))

    @mock.patch('app.main.views.services.data_api_client')
    def test_services_without_service_name_show_lot_instead(self, data_api_client):
        with self.app.test_client():
            self.login()

            data_api_client.find_services.return_value = {
                'services': [{
                    'status': 'published',
                    'id': '123',
                    'lotName': 'Special Lot Name',
                    'frameworkSlug': 'digital-outcomes-and-specialists'
                }]
            }

            res = self.client.get(self.url_for('main.list_services'))
            assert_equal(res.status_code, 200)
            data_api_client.find_services.assert_called_once_with(supplier_code=1234)

            assert "Special Lot Name" in res.get_data(as_text=True)

    @mock.patch('app.main.views.services.data_api_client')
    def test_shows_dos_service_name_without_edit_link(self, data_api_client):
        with self.app.test_client():
            self.login()

            data_api_client.find_services.return_value = {
                'services': [{
                    'serviceName': 'Service name 123',
                    'lotName': 'Special Lot Name',
                    'status': 'published',
                    'id': '123',
                    'frameworkSlug': 'digital-outcomes-and-specialists'
                }]
            }

            res = self.client.get(self.url_for('main.list_services'))
            assert_equal(res.status_code, 200)
            data_api_client.find_services.assert_called_once_with(supplier_code=1234)

            assert "Service name 123" in res.get_data(as_text=True)
            assert self.url_for('main.edit_service', service_id=123) not in res.get_data(as_text=True)


class TestListServicesLogin(BaseApplicationTest):
    @mock.patch('app.main.views.services.data_api_client')
    def test_should_show_services_list_if_logged_in(self, data_api_client):
        with self.app.test_client():
            self.login()
            data_api_client.find_services.return_value = {'services': [{
                'serviceName': 'Service name 123',
                'status': 'published',
                'id': '123',
                'frameworkSlug': 'g-cloud-1'
            }]}

            res = self.client.get(self.url_for('main.list_services'))

            assert_equal(res.status_code, 200)

            assert_true(
                self.strip_all_whitespace('<h1>Current services</h1>')
                in self.strip_all_whitespace(res.get_data(as_text=True))
            )

    def test_should_redirect_to_login_if_not_logged_in(self):
        services_url = self.url_for('main.list_services')
        res = self.client.get(services_url)
        assert_equal(res.status_code, 302)
        assert_equal(res.location, self.get_login_redirect_url(services_url))


@mock.patch('app.main.views.services.data_api_client')
class TestSupplierUpdateService(BaseApplicationTest):
    def _get_service(self,
                     data_api_client,
                     framework_slug_and_name,
                     service_status="published",
                     service_belongs_to_user=True):

        framework_slug, framework_name = framework_slug_and_name

        data_api_client.get_service.return_value = {
            'services': {
                'serviceName': 'Service name 123',
                'status': service_status,
                'id': '123',
                'frameworkName': framework_name,
                'frameworkSlug': framework_slug,
                'supplierCode': 1234 if service_belongs_to_user else 1235
            }
        }
        if service_status == 'published':
            data_api_client.update_service_status.return_value = data_api_client.get_service.return_value
        else:
            data_api_client.get_service.return_value['serviceMadeUnavailableAuditEvent'] = {
                "createdAt": "2015-03-23T09:30:00.00001Z"
            }

        data_api_client.get_framework.return_value = {
            'frameworks': {
                'name': framework_name,
                'slug': framework_slug,
                'status': 'live'
            }
        }

    def _post_remove_service(self, service_should_be_modifiable, failing_status_code=400):

        expected_status_code = \
            302 if service_should_be_modifiable else failing_status_code

        res = self.client.post(self.url_for('main.remove_service', service_id=123), data=csrf_only_request)
        assert_equal(res.status_code, expected_status_code)

    def test_should_view_public_service_with_correct_message(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(data_api_client, fixture_framework_slug_and_name, service_status='published')

        res = self.client.get(self.url_for('main.edit_service', service_id=123))
        assert_equal(res.status_code, 200)

        assert_true(
            'Service name 123' in res.get_data(as_text=True)
        )

        # first message should be there
        self.assert_in_strip_whitespace(
            'Remove this service',
            res.get_data(as_text=True)
        )

        # confirmation message should not have been triggered yet
        self.assert_not_in_strip_whitespace(
            'Are you sure you want to remove your service?',
            res.get_data(as_text=True)
        )

        # service removed message should not have been triggered yet
        self.assert_not_in_strip_whitespace(
            'Service name 123 has been removed.',
            res.get_data(as_text=True)
        )

        # service removed notification banner shouldn't be there either
        self.assert_not_in_strip_whitespace(
            '<h2>This service was removed on Monday 23 March 2015</h2>',
            res.get_data(as_text=True)
        )

        self._post_remove_service(service_should_be_modifiable=True)

    def test_should_view_private_service_with_correct_message(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(data_api_client, fixture_framework_slug_and_name, service_status='enabled')

        res = self.client.get(self.url_for('main.edit_service', service_id=123))
        assert_equal(res.status_code, 200)
        assert_true(
            'Service name 123' in res.get_data(as_text=True)
        )

        self.assert_in_strip_whitespace(
            '<h2>This service was removed on Monday 23 March 2015</h2>',
            res.get_data(as_text=True)
        )

        self.assert_not_in_strip_whitespace(
            '<h2>Remove this service</h2>',
            res.get_data(as_text=True)
        )

        self._post_remove_service(service_should_be_modifiable=False)

    def test_should_view_disabled_service_with_removed_message(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(data_api_client, fixture_framework_slug_and_name, service_status='disabled')

        res = self.client.get(self.url_for('main.edit_service', service_id=123))
        assert_equal(res.status_code, 200)
        self.assert_in_strip_whitespace(
            'Service name 123',
            res.get_data(as_text=True)
        )

        self.assert_in_strip_whitespace(
            '<h2>This service was removed on Monday 23 March 2015</h2>',
            res.get_data(as_text=True)
        )

        self._post_remove_service(service_should_be_modifiable=False)

    def test_should_view_confirmation_message_if_first_remove_service_button_clicked(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(data_api_client, fixture_framework_slug_and_name, service_status='published')

        res = self.client.post(
            self.url_for('main.remove_service', service_id=123),
            follow_redirects=True,
            data=csrf_only_request
        )

        assert_equal(res.status_code, 200)

        # first message should be gone
        self.assert_not_in_strip_whitespace(
            'Remove this service',
            res.get_data(as_text=True)
        )

        # confirmation message should be there
        self.assert_in_strip_whitespace(
            'Are you sure you want to remove your service?',
            res.get_data(as_text=True)
        )

        # service removed message should not have been triggered yet
        self.assert_not_in_strip_whitespace(
            'Service name 123 has been removed.',
            res.get_data(as_text=True)
        )

    def test_should_view_correct_notification_message_if_service_removed(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(data_api_client, fixture_framework_slug_and_name, service_status='published')

        res = self.client.post(
            self.url_for('main.remove_service', service_id=123),
            data={'remove_confirmed': True, 'csrf_token': FakeCsrf.valid_token},
            follow_redirects=True)

        assert_equal(res.status_code, 200)
        self.assert_in_strip_whitespace(
            'Service name 123 has been removed.',
            res.get_data(as_text=True)
        )

        # the "are you sure" message should be gone
        self.assert_not_in_strip_whitespace(
            'Are you sure you want to remove your service?',
            res.get_data(as_text=True)
        )

    def test_should_not_view_other_suppliers_services(
            self, data_api_client, fixture_framework_slug_and_name
    ):
        self.login()
        self._get_service(
            data_api_client, fixture_framework_slug_and_name, service_status='published', service_belongs_to_user=False)

        res = self.client.get(self.url_for('main.edit_service', service_id=123))
        assert_equal(res.status_code, 404)

        # Should all be 404 if service doesn't belong to supplier
        self._post_remove_service(service_should_be_modifiable=False, failing_status_code=404)

    def test_should_redirect_to_login_if_not_logged_in(self, data_api_client):
        edit_url = self.url_for('main.edit_service', service_id=123)
        res = self.client.get(edit_url)
        assert_equal(res.status_code, 302)
        assert_equal(res.location, self.get_login_redirect_url(edit_url))


@mock.patch('app.main.views.services.data_api_client')
class TestEditService(BaseApplicationTest):

    empty_service = {
        'services': {
            'serviceName': 'Service name 123',
            'status': 'published',
            'id': '123',
            'frameworkSlug': 'g-cloud-6',
            'frameworkName': 'G-Cloud 6',
            'supplierCode': 1234,
            'supplierName': 'We supply any',
            'lot': 'scs',
            'lotSlug': 'scs',
            'lotName': "Specialist Cloud Services",
        }
    }

    def setup(self):
        super(TestEditService, self).setup()
        with self.app.test_client():
            self.login()

    def test_return_to_service_summary_link_present(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        res = self.client.get(self.url_for('main.edit_section', service_id=1, section_id='description'))
        assert_equal(res.status_code, 200)
        link_html = '<a href="{}">Return to service summary</a>'.format(self.url_for('main.edit_service', service_id=1))
        assert_in(
            self.strip_all_whitespace(link_html),
            self.strip_all_whitespace(res.get_data(as_text=True))
        )

    def test_questions_for_this_service_section_can_be_changed(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceName': 'The service',
                'serviceSummary': 'This is the service',
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_service.assert_called_once_with(
            '1', {'serviceName': 'The service', 'serviceSummary': 'This is the service'},
            'email@email.com')

    def test_editing_readonly_section_is_not_allowed(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service

        res = self.client.get(self.url_for('main.edit_section', service_id=1, section_id='service-attributes'))
        assert_equal(res.status_code, 404)

        data_api_client.get_draft_service.return_value = self.empty_service
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='service-attributes'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'lotSlug': 'scs',
            })
        assert_equal(res.status_code, 404)

    def test_only_questions_for_this_service_section_can_be_changed(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceFeatures': '',
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_service.assert_called_one_with(
            '1', dict(), 'email@email.com')

    def test_edit_non_existent_service_returns_404(self, data_api_client):
        data_api_client.get_service.return_value = None
        res = self.client.get(self.url_for('main.edit_section', service_id=1, section_id='description'))

        assert_equal(res.status_code, 404)

    def test_edit_non_existent_section_returns_404(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        res = self.client.get(
            self.url_for('main.edit_section', service_id=1, section_id='invalid-section')
        )
        assert_equal(404, res.status_code)

    def test_update_with_answer_required_error(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        data_api_client.update_service.side_effect = HTTPError(
            mock.Mock(status_code=400),
            {'serviceSummary': 'answer_required'})
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='description'),
            data=csrf_only_request)

        assert_equal(res.status_code, 200)
        document = html.fromstring(res.get_data(as_text=True))
        assert_equal(
            "You need to answer this question.",
            document.xpath('//span[@class="validation-message"]/text()')[0].strip())

    def test_update_with_under_50_words_error(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        data_api_client.update_service.side_effect = HTTPError(
            mock.Mock(status_code=400),
            {'serviceSummary': 'under_50_words'})
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='description'),
            data=csrf_only_request)

        assert_equal(res.status_code, 200)
        document = html.fromstring(res.get_data(as_text=True))
        assert_equal(
            "Your description must be no more than 50 words.",
            document.xpath('//span[@class="validation-message"]/text()')[0].strip())

    def test_update_non_existent_service_returns_404(self, data_api_client):
        data_api_client.get_service.return_value = None
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='description'),
            data=csrf_only_request
        )

        assert_equal(res.status_code, 404)

    def test_update_non_existent_section_returns_404(self, data_api_client):
        data_api_client.get_service.return_value = self.empty_service
        res = self.client.post(
            self.url_for('main.update_section', service_id=1, section_id='invalid_section'),
            data=csrf_only_request
        )
        assert_equal(404, res.status_code)


@mock.patch('app.main.views.services.data_api_client', autospec=True)
class TestCreateDraftService(BaseApplicationTest):
    def setup(self):
        super(TestCreateDraftService, self).setup()
        self._answer_required = 'Answer is required'
        self._validation_error = 'There was a problem with your answer to:'

        with self.app.test_client():
            self.login()

    def test_get_create_draft_service_page_if_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')

        res = self.client.get(self.url_for('main.start_new_draft_service', framework_slug='g-cloud-7', lot_slug='scs'))
        assert_equal(res.status_code, 200)
        assert_in(u'Service name', res.get_data(as_text=True))

        assert_not_in(self._validation_error, res.get_data(as_text=True))

    def test_can_not_get_create_draft_service_page_if_not_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')

        res = self.client.get(self.url_for('main.start_new_draft_service', framework_slug='g-cloud-7', lot_slug='scs'))
        assert_equal(res.status_code, 404)

    def _test_post_create_draft_service(self, data, if_error_expected, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.create_new_draft_service.return_value = {"services": empty_g7_draft()}

        res = self.client.post(
            self.url_for('main.create_new_draft_service', framework_slug='g-cloud-7', lot_slug='scs'),
            data=data
        )

        if if_error_expected:
            assert_equal(res.status_code, 400)
            assert_in(self._validation_error, res.get_data(as_text=True))
        else:
            assert_equal(res.status_code, 302)

    def test_post_create_draft_service_succeeds(self, data_api_client):
        self._test_post_create_draft_service(
            {'serviceName': 'Service Name', 'csrf_token': FakeCsrf.valid_token},
            if_error_expected=False, data_api_client=data_api_client
        )

    def test_post_create_draft_service_with_api_error_fails(self, data_api_client):
        data_api_client.create_new_draft_service.side_effect = HTTPError(
            mock.Mock(status_code=400),
            {'serviceName': 'answer_required'}
        )

        self._test_post_create_draft_service(
            csrf_only_request,
            if_error_expected=True, data_api_client=data_api_client
        )

        res = self.client.post(
            self.url_for('main.create_new_draft_service', framework_slug='g-cloud-7', lot_slug='scs'),
            data=csrf_only_request
        )

        assert_equal(res.status_code, 400)
        assert_in(self._validation_error, res.get_data(as_text=True))

    def test_cannot_post_if_not_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')
        res = self.client.post(
            self.url_for('main.create_new_draft_service', framework_slug='g-cloud-7', lot_slug='scs'),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 404)


@mock.patch('app.main.views.services.data_api_client')
class TestCopyDraft(BaseApplicationTest):

    def setup(self):
        super(TestCopyDraft, self).setup()

        with self.app.test_client():
            self.login()

        self.draft = empty_g7_draft()

    def test_copy_draft(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = {'services': self.draft}

        res = self.client.post(
            self.url_for('main.copy_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 302)

    def test_copy_draft_checks_supplier_code(self, data_api_client):
        self.draft['supplierCode'] = 2
        data_api_client.get_draft_service.return_value = {'services': self.draft}

        res = self.client.post(
            self.url_for('main.copy_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 404)

    def test_cannot_copy_draft_if_not_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')

        res = self.client.post(
            self.url_for('main.copy_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 404)


@mock.patch('app.main.views.services.data_api_client')
class TestCompleteDraft(BaseApplicationTest):

    def setup(self):
        super(TestCompleteDraft, self).setup()

        with self.app.test_client():
            self.login()

        self.draft = empty_g7_draft()

    def test_complete_draft(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = {'services': self.draft}
        res = self.client.post(
            self.url_for('main.complete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 302)
        target_url = self.url_for(
            'main.framework_submission_services',
            framework_slug='g-cloud-7',
            lot='scs',
            lot_slug='scs',
            _external=True
        )
        assert_equal(res.location, target_url)

    def test_complete_draft_checks_supplier_code(self, data_api_client):
        self.draft['supplierCode'] = 2
        data_api_client.get_draft_service.return_value = {'services': self.draft}

        res = self.client.post(
            self.url_for('main.complete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 404)

    def test_cannot_complete_draft_if_not_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')

        res = self.client.post(
            self.url_for('main.complete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 404)


@mock.patch('dmutils.s3.S3')
@mock.patch('app.main.views.services.data_api_client')
class TestEditDraftService(BaseApplicationTest):

    def setup(self):
        super(TestEditDraftService, self).setup()
        with self.app.test_client():
            self.login()

        self.empty_draft = {'services': empty_g7_draft()}

        self.multiquestion_draft = {
            'services': {
                'id': 1,
                'supplierCode': 1234,
                'supplierName': 'supplierName',
                'lot': 'digital-specialists',
                'lotSlug': 'digital-specialists',
                'frameworkSlug': 'digital-outcomes-and-specialists',
                'lotName': 'Digital specialists',
                'agileCoachLocations': ['Wales'],
                'agileCoachPriceMax': '200',
                'agileCoachPriceMin': '100',
                'developerLocations': ['Wales'],
                'developerPriceMax': '250',
                'developerPriceMin': '150',
                'status': 'not-submitted',
            },
            'auditEvents': {
                'createdAt': '2015-06-29T15:26:07.650368Z',
                'userName': 'Supplier User',
            },
            'validationErrors': {}
        }

    def test_questions_for_this_draft_section_can_be_changed(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceSummary': 'This is the service',
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1',
            {'serviceSummary': 'This is the service'},
            'email@email.com',
            page_questions=['serviceSummary']
        )

    def test_update_without_changes_is_not_sent_to_the_api(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        draft = self.empty_draft['services'].copy()
        draft.update({'serviceSummary': u"summary"})
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = {'services': draft}

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceSummary': u"summary",
            })

        assert_equal(res.status_code, 302)
        assert_false(data_api_client.update_draft_service.called)

    def test_S3_should_not_be_called_if_there_are_no_files(self, data_api_client, s3):
        uploader = mock.Mock()
        s3.return_value = uploader
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceSummary': 'This is the service',
            })

        assert_equal(res.status_code, 302)
        assert not uploader.save.called

    def test_editing_readonly_section_is_not_allowed(self, data_api_client, s3):
        data_api_client.get_draft_service.return_value = self.empty_draft

        res = self.client.get(
            self.url_for(
                'main.edit_service_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-attributes'))
        assert_equal(res.status_code, 404)

        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-attributes'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'lotSlug': 'scs',
            })
        assert_equal(res.status_code, 404)

    def test_draft_section_cannot_be_edited_if_not_open(self, data_api_client, s3):
        data_api_client.get_framework.return_value = self.framework(status='other')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceSummary': 'This is the service',
            })
        assert_equal(res.status_code, 404)

    def test_only_questions_for_this_draft_section_can_be_changed(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceFeatures': '',
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1', {}, 'email@email.com',
            page_questions=['serviceSummary']
        )

    def test_display_file_upload_with_existing_file(self, data_api_client, s3):
        draft = copy.deepcopy(self.empty_draft)
        draft['services']['serviceDefinitionDocumentURL'] = 'http://localhost/fooo-2012-12-12-1212.pdf'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = draft
        response = self.client.get(
            self.url_for(
                'main.edit_service_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-definition')
        )
        document = html.fromstring(response.get_data(as_text=True))

        assert_equal(response.status_code, 200)
        assert_equal(len(document.cssselect('p.file-upload-existing-value')), 1)

    def test_display_file_upload_with_no_existing_file(self, data_api_client, s3):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        response = self.client.get(
            self.url_for(
                'main.edit_service_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-definition')
        )
        document = html.fromstring(response.get_data(as_text=True))

        assert_equal(response.status_code, 200)
        assert_equal(len(document.cssselect('p.file-upload-existing-value')), 0)

    def test_file_upload(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        with freeze_time('2015-01-02 03:04:05'):
            res = self.client.post(
                self.url_for(
                    'main.update_section_submission',
                    framework_slug='g-cloud-7',
                    lot_slug='scs',
                    service_id=1,
                    section_id='service-definition'),
                data={
                    'csrf_token': FakeCsrf.valid_token,
                    'serviceDefinitionDocumentURL': (StringIO(b'doc'), 'document.pdf'),
                }
            )

        assert_equal(res.status_code, 302)
        document_url = self.url_for(
            'main.service_submission_document',
            framework_slug='g-cloud-7',
            supplier_code='1234',
            document_name='1-service-definition-document-2015-01-02-0304.pdf',
            _external=True
        )
        data_api_client.update_draft_service.assert_called_once_with(
            '1', {
                'serviceDefinitionDocumentURL': document_url
            }, 'email@email.com',
            page_questions=['serviceDefinitionDocumentURL']
        )

        s3.return_value.save.assert_called_once_with(
            'g-cloud-7/submissions/1234/1-service-definition-document-2015-01-02-0304.pdf',
            mock.ANY, acl='private'
        )

    def test_file_upload_filters_empty_and_unknown_files(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-definition'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceDefinitionDocumentURL': (StringIO(b''), 'document.pdf'),
                'unknownDocumentURL': (StringIO(b'doc'), 'document.pdf'),
                'pricingDocumentURL': (StringIO(b'doc'), 'document.pdf'),
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1', {}, 'email@email.com',
            page_questions=['serviceDefinitionDocumentURL']
        )

        assert_false(s3.return_value.save.called)

    def test_upload_question_not_accepted_as_form_data(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-definition'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'serviceDefinitionDocumentURL': 'http://example.com/document.pdf',
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1', {}, 'email@email.com',
            page_questions=['serviceDefinitionDocumentURL']
        )

    def test_pricing_fields_are_added_correctly(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='pricing'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'priceMin': "10.10",
                'priceMax': "11.10",
                'priceUnit': "Person",
                'priceInterval': "Second",
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1',
            {
                'priceMin': "10.10", 'priceMax': "11.10", "priceUnit": "Person", 'priceInterval': 'Second',
            },
            'email@email.com',
            page_questions=[
                'priceInterval', 'priceMax', 'priceMin', 'priceUnit',
                'vatIncluded', 'educationPricing',
            ])

    def test_edit_non_existent_draft_service_returns_404(self, data_api_client, s3):
        data_api_client.get_draft_service.side_effect = HTTPError(mock.Mock(status_code=404))
        res = self.client.get(self.url_for(
            'main.edit_service_submission',
            framework_slug='g-cloud-7',
            lot_slug='scs',
            service_id=1,
            section_id='service-description'))

        assert_equal(res.status_code, 404)

    def test_edit_non_existent_draft_section_returns_404(self, data_api_client, s3):
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.get(
            self.url_for(
                'main.edit_service_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='invalid_section')
        )
        assert_equal(404, res.status_code)

    def test_update_redirects_to_next_editable_section(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.return_value = None

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'continue_to_next_section': 'Save and continue'
            })

        assert_equal(302, res.status_code)
        expected_location = self.url_for(
            'main.edit_service_submission',
            framework_slug='g-cloud-7',
            lot_slug='scs',
            service_id=1,
            section_id='service-type',
            _external=True
        )
        assert_equal(expected_location, res.headers['Location'])

    def test_update_redirects_to_edit_submission_if_no_next_editable_section(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.return_value = None

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='sfia-rate-card'),
            data=csrf_only_request)

        assert_equal(302, res.status_code)
        expected_location = self.url_for(
            'main.view_service_submission',
            framework_slug='g-cloud-7',
            lot_slug='scs',
            service_id=1,
            _external=True
        ) + '#sfia-rate-card'
        assert_equal(expected_location, res.headers['Location'])

    def test_update_redirects_to_edit_submission_if_return_to_summary(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.return_value = None

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description',
                return_to_summary=1),
            data=csrf_only_request)

        assert_equal(302, res.status_code)
        expected_location = self.url_for(
            'main.view_service_submission',
            framework_slug='g-cloud-7',
            lot_slug='scs',
            service_id=1,
            _external=True
        ) + '#service-description'
        assert_equal(expected_location, res.headers['Location'])

    def test_update_redirects_to_edit_submission_if_save_and_return_grey_button_clicked(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.return_value = None

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data=csrf_only_request)

        assert_equal(302, res.status_code)
        expected_location = self.url_for(
            'main.view_service_submission',
            framework_slug='g-cloud-7',
            lot_slug='scs',
            service_id=1,
            _external=True
        ) + '#service-description'
        assert_equal(expected_location, res.headers['Location'])

    def test_update_with_answer_required_error(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.side_effect = HTTPError(
            mock.Mock(status_code=400),
            {'serviceSummary': 'answer_required'})
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data=csrf_only_request)

        assert_equal(res.status_code, 200)
        document = html.fromstring(res.get_data(as_text=True))
        assert_equal(
            "You need to answer this question.",
            document.xpath('//span[@class="validation-message"]/text()')[0].strip())

    def test_update_with_under_50_words_error(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.empty_draft
        data_api_client.update_draft_service.side_effect = HTTPError(
            mock.Mock(status_code=400),
            {'serviceSummary': 'under_50_words'})
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data=csrf_only_request)

        assert_equal(res.status_code, 200)
        document = html.fromstring(res.get_data(as_text=True))
        assert_equal(
            "Your description must be no more than 50 words.",
            document.xpath('//span[@class="validation-message"]/text()')[0].strip())

    def test_update_with_pricing_errors(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        cases = [
            ('priceMin', 'answer_required', 'Minimum price requires an answer.'),
            ('priceUnit', 'answer_required', "Pricing unit requires an answer. If none of the provided units apply, please choose 'Unit'."),  # noqa
            ('priceMin', 'not_money_format', 'Minimum price must be a number, without units, eg 99.95'),
            ('priceMax', 'not_money_format', 'Maximum price must be a number, without units, eg 99.95'),
            ('priceMax', 'max_less_than_min', 'Minimum price must be less than maximum price'),
        ]

        for field, error, message in cases:
            data_api_client.get_framework.return_value = self.framework(status='open')
            data_api_client.get_draft_service.return_value = self.empty_draft
            data_api_client.update_draft_service.side_effect = HTTPError(
                mock.Mock(status_code=400),
                {field: error})
            res = self.client.post(
                self.url_for(
                    'main.update_section_submission',
                    framework_slug='g-cloud-7',
                    lot_slug='scs',
                    service_id=1,
                    section_id='pricing'),
                data=csrf_only_request)

            assert_equal(res.status_code, 200)
            document = html.fromstring(res.get_data(as_text=True))
            assert_equal(
                message, document.xpath('//span[@class="validation-message"]/text()')[0].strip())

    def test_update_non_existent_draft_service_returns_404(self, data_api_client, s3):
        data_api_client.get_draft_service.side_effect = HTTPError(mock.Mock(status_code=404))
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='service-description'),
            data=csrf_only_request
        )

        assert_equal(res.status_code, 404)

    def test_update_non_existent_draft_section_returns_404(self, data_api_client, s3):
        data_api_client.get_draft_service.return_value = self.empty_draft
        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                section_id='invalid-section'),
            data=csrf_only_request
        )
        assert_equal(404, res.status_code)

    def test_update_multiquestion(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(
            status='open', slug='digital-outcomes-and-specialists'
        )
        draft = self.empty_draft.copy()
        draft['services']['lot'] = 'digital-specialists'
        draft['services']['lotSlug'] = 'digital-specialists'
        draft['services']['frameworkSlug'] = 'digital-outcomes-and-specialists'
        data_api_client.get_draft_service.return_value = draft

        res = self.client.get(
            self.url_for(
                'main.edit_service_submission',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach'))

        assert_equal(res.status_code, 200)

        res = self.client.post(
            self.url_for(
                'main.update_section_submission',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach'),
            data={
                'csrf_token': FakeCsrf.valid_token,
                'agileCoachLocations': ['Scotland'],
            })

        assert_equal(res.status_code, 302)
        data_api_client.update_draft_service.assert_called_once_with(
            '1',
            {'agileCoachLocations': ['Scotland']},
            'email@email.com',
            page_questions=['agileCoachLocations', 'agileCoachPriceMax', 'agileCoachPriceMin']
        )

    def test_remove_subsection(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(
            status='open', slug='digital-outcomes-and-specialists'
        )

        data_api_client.get_draft_service.return_value = self.multiquestion_draft

        res = self.client.get(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach'))

        view_service_submission_url = self.url_for(
            'main.view_service_submission',
            framework_slug='digital-outcomes-and-specialists',
            lot_slug='digital-specialists',
            service_id=1
        )
        assert_equal(res.status_code, 302)
        assert view_service_submission_url in res.location
        assert('section_id=individual-specialist-roles' in res.location)
        assert('confirm_remove=agile-coach' in res.location)

        res2 = self.client.get(
            self.url_for(
                'main.view_service_submission',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='specialists',
                confirm_remove='agile-coach'))
        assert_equal(res2.status_code, 200)
        assert_in(u'Are you sure you want to remove agile coach?', res2.get_data(as_text=True))

        res3 = self.client.post(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach',
                confirm=True),
            data=csrf_only_request)

        assert_equal(res3.status_code, 302)
        assert res3.location.endswith(view_service_submission_url)
        data_api_client.update_draft_service.assert_called_once_with(
            '1',
            {
                'agileCoachLocations': None,
                'agileCoachPriceMax': None,
                'agileCoachPriceMin': None,
            },
            'email@email.com'
        )

    def test_can_not_remove_last_subsection_from_submitted_draft(self, data_api_client, s3):
        s3.return_value.bucket_short_name = 'submissions'
        data_api_client.get_framework.return_value = self.framework(
            status='open', slug='digital-outcomes-and-specialists'
        )

        draft_service = copy.deepcopy(self.multiquestion_draft)
        draft_service['services'].pop('developerLocations', None)
        draft_service['services'].pop('developerPriceMax', None)
        draft_service['services'].pop('developerPriceMin', None)
        draft_service['services']['status'] = 'submitted'

        data_api_client.get_draft_service.return_value = draft_service

        res = self.client.get(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach'))

        assert_equal(res.status_code, 302)
        view_service_submission_url = self.url_for(
            'main.view_service_submission',
            framework_slug='digital-outcomes-and-specialists',
            lot_slug='digital-specialists',
            service_id=1
        )
        assert res.location.endswith(view_service_submission_url)

        res2 = self.client.get(view_service_submission_url)
        assert_equal(res2.status_code, 200)
        assert_in("You must offer one of the individual specialist roles to be eligible.",
                  res2.get_data(as_text=True))

        data_api_client.update_draft_service.assert_not_called()

    def test_can_not_remove_other_suppliers_subsection(self, data_api_client, s3):
        draft_service = copy.deepcopy(self.multiquestion_draft)
        draft_service['services']['supplierCode'] = 12345
        data_api_client.get_draft_service.return_value = draft_service
        res = self.client.post(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach',
                confirm=True
            ),
            data=csrf_only_request
        )

        assert_equal(res.status_code, 404)
        data_api_client.update_draft_service.assert_not_called()

    def test_fails_if_api_get_fails(self, data_api_client, s3):
        data_api_client.get_draft_service.side_effect = HTTPError(mock.Mock(status_code=504))
        res = self.client.post(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach',
                confirm=True
            ),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 504)

    def test_fails_if_api_update_fails(self, data_api_client, s3):
        data_api_client.get_draft_service.return_value = self.multiquestion_draft
        data_api_client.update_draft_service.side_effect = HTTPError(mock.Mock(status_code=504))
        res = self.client.post(
            self.url_for(
                'main.remove_subsection',
                framework_slug='digital-outcomes-and-specialists',
                lot_slug='digital-specialists',
                service_id=1,
                section_id='individual-specialist-roles',
                question_slug='agile-coach',
                confirm=True
            ),
            data=csrf_only_request
        )
        assert_equal(res.status_code, 504)


@mock.patch('app.main.views.services.data_api_client')
class TestShowDraftService(BaseApplicationTest):

    draft_service_data = empty_g7_draft()
    draft_service_data.update({
        'priceMin': '12.50',
        'priceMax': '15',
        'priceUnit': 'Person',
        'priceInterval': 'Second',
    })

    draft_service = {
        'services': draft_service_data,
        'auditEvents': {
            'createdAt': '2015-06-29T15:26:07.650368Z',
            'userName': 'Supplier User',
        },
        'validationErrors': {}
    }

    complete_service = copy.deepcopy(draft_service)
    complete_service['services']['status'] = 'submitted'
    complete_service['services']['id'] = 2

    def setup(self):
        super(TestShowDraftService, self).setup()
        with self.app.test_client():
            self.login()

    def test_service_price_is_correctly_formatted(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework('open')
        data_api_client.get_draft_service.return_value = self.draft_service
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        document = html.fromstring(res.get_data(as_text=True))

        assert_equal(res.status_code, 200)
        service_price_row_xpath = '//tr[contains(.//span/text(), "Service price")]'
        service_price_xpath = service_price_row_xpath + '/td[@class="summary-item-field"]/span/text()'
        assert_equal(
            document.xpath(service_price_xpath)[0].strip(),
            u"$12.50 to $15 per person per second")

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_unanswered_questions_count(self, count_unanswered, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.draft_service
        count_unanswered.return_value = 1, 2
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        assert_equal(res.status_code, 200)
        assert_true(u'3 unanswered questions' in res.get_data(as_text=True),
                    "'3 unanswered questions' not found in html")

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_move_to_complete_button(self, count_unanswered, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.draft_service
        count_unanswered.return_value = 0, 1
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        assert_equal(res.status_code, 200)
        assert_in(u'1 optional question unanswered', res.get_data(as_text=True))
        assert_in(u'<input type="submit" class="button-save" value="Mark as complete"/>'.replace(' ', ''),
                  res.get_data(as_text=True).replace(' ', ''))

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_no_move_to_complete_button_if_not_open(self, count_unanswered, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')
        data_api_client.get_draft_service.return_value = self.draft_service
        count_unanswered.return_value = 0, 1
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        assert_equal(res.status_code, 404)
        assert_not_in(u'<input type="submit" class="button-save" value="Mark as complete"/>'.replace(' ', ''),
                      res.get_data(as_text=True).replace(' ', ''))

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_no_move_to_complete_button_if_validation_errors(self, count_unanswered, data_api_client):
        draft_service = copy.deepcopy(self.draft_service)
        draft_service['validationErrors'] = {'_errors': "Everything's busted"}

        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = draft_service
        count_unanswered.return_value = 0, 1

        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        assert_equal(res.status_code, 200)
        assert_not_in(u'<input type="submit" class="button-save"  value="Mark as complete" />',
                      res.get_data(as_text=True))

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_shows_g7_message_if_pending_and_service_is_in_draft(self, count_unanswered, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='pending')
        data_api_client.get_draft_service.return_value = self.draft_service
        count_unanswered.return_value = 3, 1
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=1)
        )

        assert_equal(res.status_code, 200)
        doc = html.fromstring(res.get_data(as_text=True))
        message = doc.xpath('//aside[@class="temporary-message"]')

        assert_true(len(message) > 0)
        assert_in(u"This service was not submitted",
                  message[0].xpath('h2[@class="temporary-message-heading"]/text()')[0])
        assert_in(u"It wasn't marked as complete at the deadline.",
                  message[0].xpath('p[@class="temporary-message-message"]/text()')[0])

    @mock.patch('app.main.views.services.count_unanswered_questions')
    def test_shows_g7_message_if_pending_and_service_is_complete(self, count_unanswered, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='pending')
        data_api_client.get_draft_service.return_value = self.complete_service
        count_unanswered.return_value = 0, 1
        res = self.client.get(
            self.url_for('main.view_service_submission', framework_slug='g-cloud-7', lot_slug='scs', service_id=2)
        )

        assert_equal(res.status_code, 200)
        doc = html.fromstring(res.get_data(as_text=True))
        message = doc.xpath('//aside[@class="temporary-message"]')

        assert_true(len(message) > 0)
        assert_in(u"This service was submitted",
                  message[0].xpath('h2[@class="temporary-message-heading"]/text()')[0])
        assert_in(u"If your application is successful, it will be available on the Digital Marketplace when G-Cloud 7 goes live.",  # noqa
                  message[0].xpath('p[@class="temporary-message-message"]/text()')[0])


@mock.patch('app.main.views.services.data_api_client')
class TestDeleteDraftService(BaseApplicationTest):

    draft_service_data = empty_g7_draft()
    draft_service_data.update({
        'serviceName': 'My rubbish draft',
        'serviceSummary': 'This is the worst service ever',
    })
    draft_to_delete = {
        'services': draft_service_data,
        'auditEvents': {
            'createdAt': "2015-06-29T15:26:07.650368Z",
            'userName': "Supplier User",
        },
        'validationErrors': {}
    }

    def setup(self):
        super(TestDeleteDraftService, self).setup()
        with self.app.test_client():
            self.login()

    def test_delete_button_redirects_with_are_you_sure(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.draft_to_delete
        res = self.client.post(
            self.url_for('main.delete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request)
        assert_equal(res.status_code, 302)
        assert_in('/frameworks/g-cloud-7/submissions/scs/1?delete_requested=True', res.location)
        res2 = self.client.get(
            self.url_for(
                'main.view_service_submission',
                framework_slug='g-cloud-7',
                lot_slug='scs',
                service_id=1,
                delete_requested=True)
        )
        assert_in(
            b"Are you sure you want to delete this service?", res2.get_data()
        )

    def test_cannot_delete_if_not_open(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='other')
        data_api_client.get_draft_service.return_value = self.draft_to_delete
        res = self.client.post(
            self.url_for('main.delete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data=csrf_only_request)
        assert_equal(res.status_code, 404)

    def test_confirm_delete_button_deletes_and_redirects_to_dashboard(self, data_api_client):
        data_api_client.get_framework.return_value = self.framework(status='open')
        data_api_client.get_draft_service.return_value = self.draft_to_delete
        res = self.client.post(
            self.url_for('main.delete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data={'delete_confirmed': 'true', 'csrf_token': FakeCsrf.valid_token})

        data_api_client.delete_draft_service.assert_called_with('1', 'email@email.com')
        assert_equal(res.status_code, 302)
        assert_equal(
            res.location,
            self.url_for('main.framework_submission_services', framework_slug='g-cloud-7', lot_slug='scs', _external=True)  # noqa
        )

    def test_cannot_delete_other_suppliers_draft(self, data_api_client):
        other_draft = copy.deepcopy(self.draft_to_delete)
        other_draft['services']['supplierCode'] = 12345
        data_api_client.get_draft_service.return_value = other_draft
        res = self.client.post(
            self.url_for('main.delete_draft_service', framework_slug='g-cloud-7', lot_slug='scs', service_id=1),
            data={'delete_confirmed': 'true', 'csrf_token': FakeCsrf.valid_token})

        assert_equal(res.status_code, 404)


@mock.patch('dmutils.s3.S3')
class TestSubmissionDocuments(BaseApplicationTest):
    def setup(self):
        super(TestSubmissionDocuments, self).setup()
        with self.app.test_client():
            self.login()

    def test_document_url(self, s3):
        s3.return_value.bucket_short_name = 'submissions'
        s3.return_value.get_signed_url.return_value = 'http://example.com/document.pdf'

        res = self.client.get(
            self.url_for(
                'main.service_submission_document',
                framework_slug='g-cloud-7',
                supplier_code='1234',
                document_name='document.pdf'
            )
        )

        assert_equal(res.status_code, 302)
        assert_equal(
            res.headers['Location'],
            'http://asset-host/document.pdf'
        )

    def test_missing_document_url(self, s3):
        s3.return_value.bucket_short_name = 'submissions'
        s3.return_value.get_signed_url.return_value = None

        res = self.client.get(
            self.url_for(
                'main.service_submission_document',
                framework_slug='g-cloud-7',
                supplier_code='1234',
                document_name='document.pdf'
            )
        )

        assert_equal(res.status_code, 404)

    def test_document_url_not_matching_user_supplier(self, s3):
        res = self.client.get(
            self.url_for(
                'main.service_submission_document',
                framework_slug='g-cloud-7',
                supplier_code='999',
                document_name='document.pdf'
            )
        )

        assert_equal(res.status_code, 404)
